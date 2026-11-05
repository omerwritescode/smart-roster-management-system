"""Randomised companies: the solver must never break a hard rule, whatever the input.

The validator is the judge, so a solver bug and a validator bug would have to agree
exactly for a broken roster to slip through.
"""
from datetime import date, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.engine import domain as d
from backend.engine.repair import DayEdit, apply_edit, repair
from backend.engine.solver import SolveOptions, solve
from backend.engine.validator import validate

from .factory import COVERAGE, EARLY, GENERAL, LATE, NEVER_BROKEN

CALENDARS = [d.ALL_DAYS, d.DAILY_EXCEPT_HOLIDAYS, d.SUNDAYS_HOLIDAYS_OFF, d.CUSTOM]
ROLES = [d.PRIMARY, d.PRIMARY, d.SECONDARY, d.BACKUP]
SHIFT_IDS = ["g", "e", "l"]
FEB = date(2027, 2, 1)  # 28 days keeps each generated case small

employee_st = st.fixed_dictionaries({
    "policy": st.sampled_from(["solver", "solver", "fixed", "rotating"]),
    "fixed": st.lists(st.integers(0, 6), min_size=1, max_size=2, unique=True),
    "rotation": st.lists(st.integers(0, 6), min_size=1, max_size=4),
    "offs": st.integers(1, 2),
    "max_days": st.integers(3, 7),
    "stretch": st.sampled_from([100, 125, 150]),
})
process_st = st.fixed_dictionaries({
    "calendar": st.sampled_from(CALENDARS),
    "mask": st.lists(st.integers(0, 6), min_size=1, max_size=7, unique=True),
    "shift": st.sampled_from(SHIFT_IDS),
    "min_staff": st.integers(1, 3),
    "date_rule": st.none() | st.tuples(st.integers(0, 27), st.integers(0, 3)),
    "weekday_rule": st.none() | st.tuples(st.integers(0, 6), st.integers(0, 3)),
})
company_st = st.fixed_dictionaries({
    "employees": st.lists(employee_st, min_size=1, max_size=5),
    "processes": st.lists(process_st, min_size=1, max_size=5),
    "allocs": st.lists(st.tuples(st.integers(0, 4), st.integers(0, 4), st.sampled_from(ROLES), st.sampled_from([25, 50, 70, 100])), max_size=12),
    "leaves": st.lists(st.tuples(st.integers(0, 4), st.integers(0, 27), st.integers(0, 6), st.sampled_from(["planned", "sick", "comp_off", "unavailable"])), max_size=4),
    "holidays": st.lists(st.integers(0, 27), max_size=2, unique=True),
    "prefs": st.lists(st.tuples(st.integers(0, 4), st.integers(0, 6), st.integers(1, 5)), max_size=4),
    "history_off": st.booleans(),
    "history_shift": st.none() | st.sampled_from(SHIFT_IDS),
})


def build(spec) -> d.RosterInput:
    employees = [
        d.Employee(
            id=f"e{i}", name=f"E{i}", pod_id="p", weekly_off_policy=x["policy"],
            fixed_off_weekdays=tuple(x["fixed"]), rotation_weekdays=tuple(x["rotation"]),
            offs_per_week=x["offs"], max_consecutive_days=x["max_days"], stretch_limit=x["stretch"],
        )
        for i, x in enumerate(spec["employees"])
    ]
    bps, rules, procs = [], [], []
    for i, x in enumerate(spec["processes"]):
        bps.append(d.BrandProcess(f"bp{i}", f"b{i % 3}", f"pr{i}", x["shift"], x["calendar"], tuple(x["mask"])))
        procs.append(d.Process(f"pr{i}", f"P{i}", f"P{i}"))
        rules.append(d.CoverageRule(f"bp{i}", "default", x["min_staff"]))
        if x["date_rule"]:
            rules.append(d.CoverageRule(f"bp{i}", "date", x["date_rule"][1], date=FEB + timedelta(days=x["date_rule"][0])))
        if x["weekday_rule"]:
            rules.append(d.CoverageRule(f"bp{i}", "weekday", x["weekday_rule"][1], weekday=x["weekday_rule"][0]))
    allocs, seen = [], set()
    for ei, pi, role, share in spec["allocs"]:
        if ei < len(employees) and pi < len(bps) and (ei, pi) not in seen:
            seen.add((ei, pi))
            allocs.append(d.Allocation(f"a{ei}-{pi}", f"e{ei}", f"bp{pi}", role, share))
    leaves = []
    for n, (ei, start, length, kind) in enumerate(spec["leaves"]):
        if ei < len(employees):
            first = FEB + timedelta(days=start)
            leaves.append(d.Leave(f"l{n}", f"e{ei}", kind, "approved", first, first + timedelta(days=length)))
    prefs = [
        d.Preference(f"e{ei}", "off_weekday", weekday=w, weight=wt)
        for ei, w, wt in spec["prefs"] if ei < len(employees)
    ]
    history = []
    if spec["history_off"] or spec["history_shift"]:
        for e in employees:
            for back in range(1, 8):
                day = FEB - timedelta(days=back)
                status = d.WEEKLY_OFF if spec["history_off"] and back == 1 else d.WORK
                shifts = (spec["history_shift"],) if status == d.WORK and spec["history_shift"] else ()
                history.append(d.HistoryDay(e.id, day, status, shifts))
    return d.RosterInput(
        year=2027, month=2, employees=employees, shifts=[GENERAL, EARLY, LATE],
        brands=[d.Brand(f"b{i}", f"B{i}", "p") for i in range(3)], processes=procs, brand_processes=bps,
        coverage_rules=rules, allocations=allocs, leaves=leaves, preferences=prefs,
        holidays=[d.Holiday(FEB + timedelta(days=x), "H") for x in spec["holidays"]], history=history,
    )


COMMON = dict(deadline=None, suppress_health_check=[HealthCheck.too_slow], derandomize=True)


@settings(max_examples=120, **COMMON)
@given(company_st)
def test_solver_never_breaks_a_hard_rule(spec):
    inp = build(spec)
    result = solve(inp, SolveOptions(time_limit=4, workers=2))
    issues = validate(inp, result.roster)
    broken = [i.message for i in issues if i.code in NEVER_BROKEN]
    assert not broken, broken
    # Every gap the solver admits, the validator reports, and nothing else.
    reported = sum(i.facts["short_by"] for i in issues if i.code in COVERAGE)
    assert reported == sum(result.uncovered.values())


@settings(max_examples=40, **COMMON)
@given(company_st, st.integers(0, 4), st.integers(1, 26))
def test_repair_keeps_the_past_and_breaks_no_hard_rule(spec, who, start):
    inp = build(spec)
    base = solve(inp, SolveOptions(time_limit=3, workers=2)).roster
    emp = inp.employees[who % len(inp.employees)]
    start_day = FEB + timedelta(days=start)
    changed = d.RosterInput(**{**inp.__dict__, "leaves": [
        *inp.leaves, d.Leave("new", emp.id, "unavailable", "approved", start_day, start_day)]})
    result = repair(changed, base, start_day, time_limit=3, workers=2)
    for (e, x), rec in base.days.items():
        if x < start_day:
            assert result.roster.days[(e, x)].status == rec.status
    issues = validate(changed, result.roster)
    # Days before the change are frozen, so a rule broken only by the frozen past cannot be fixed.
    future_broken = [
        i.message for i in issues
        if i.code in NEVER_BROKEN and i.date is not None and i.date >= start_day
        and i.code not in {"WEEKLY_OFF_MISSING", "MAX_CONSECUTIVE_EXCEEDED"}
    ]
    assert not future_broken, future_broken


@settings(max_examples=30, **COMMON)
@given(company_st, st.integers(0, 4), st.integers(0, 27))
def test_any_manual_edit_can_be_validated_and_solved_around(spec, who, day_index):
    """A manual override that breaks a rule is flagged, and the solver still returns a roster."""
    inp = build(spec)
    base = solve(inp, SolveOptions(time_limit=2, workers=2)).roster
    emp = inp.employees[who % len(inp.employees)]
    day = FEB + timedelta(days=day_index)
    all_bps = tuple(b.id for b in inp.brand_processes)
    edited = apply_edit(inp, base, DayEdit(emp.id, day, d.WORK, all_bps))
    assert isinstance(validate(inp, edited), list)
    result = repair(inp, edited, FEB, time_limit=2, workers=2)
    assert result.roster.days[(emp.id, day)].status in d.ALL_STATUSES
    on_approved_leave = any(lv.employee_id == emp.id and lv.start <= day <= lv.end for lv in inp.leaves)
    assert result.roster.days[(emp.id, day)].locked != on_approved_leave  # released only for approved leave
