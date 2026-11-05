"""Solver behaviour. Every result is judged by the validator, not by the solver."""
from datetime import date

import pytest

from backend.engine import domain as d
from backend.engine import plans
from backend.engine.solver import SolveOptions, solve
from backend.engine.validator import validate

from .factory import COVERAGE, NEVER_BROKEN, company, of
from .sample import sample_input

DEC = lambda day: date(2026, 12, day)  # noqa: E731
FAST = dict(time_limit=5, workers=2)


def run(inp, **kwargs):
    result = solve(inp, SolveOptions(**{**FAST, **kwargs}))
    issues = validate(inp, result.roster)
    assert not [i for i in issues if i.code in NEVER_BROKEN], [i.message for i in issues if i.code in NEVER_BROKEN]
    gaps = [i for i in issues if i.code in COVERAGE]
    assert sum(i.facts["short_by"] for i in gaps) == sum(result.uncovered.values())
    return result, issues, gaps


def test_single_employee_seven_day_brand_without_backup_shows_real_gaps():
    """Weekly offs are never removed to hide a gap."""
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")])
    result, issues, gaps = run(inp)
    assert len(gaps) == 4
    assert result.fewest_gaps_proved
    assert of(issues, "NO_BACKUP_CONFIGURED")
    assert all(i.facts["causes"] == ["weekly_off"] for i in gaps)


def test_backup_closes_the_weekly_off_gap():
    inp = company(("p", d.ALL_DAYS, "g"), employees=("a", "b"), allocations=[("a", "p"), ("b", "p", d.BACKUP, 100)])
    result, _, gaps = run(inp)
    assert gaps == []
    cover_days = {a.date for a in result.roster.assignments if a.is_cover}
    a_off = {x for (e, x), r in result.roster.days.items() if e == "a" and r.status == d.WEEKLY_OFF}
    assert a_off <= cover_days


def test_backup_only_used_when_needed():
    inp = company(("p", d.ALL_DAYS, "g"), employees=("a", "b"), allocations=[("a", "p"), ("b", "p", d.BACKUP, 100)])
    result, _, _ = run(inp)
    worked_a = {a.date for a in result.roster.assignments if a.employee_id == "a"}
    worked_b = {a.date for a in result.roster.assignments if a.employee_id == "b"}
    assert not (worked_a & worked_b)


def test_brand_calendar_differs_from_employee_schedule():
    inp = company(("all", d.ALL_DAYS, "g"), ("sh", d.SUNDAYS_HOLIDAYS_OFF, "g"), employees=("a", "b", "c"),
                  allocations=[("a", "all"), ("b", "sh"), ("c", "all", d.BACKUP, 100)])
    result, _, gaps = run(inp)
    assert gaps == []
    assert not [a for a in result.roster.assignments if a.brand_process_id == "sh" and a.date.weekday() == 6]
    assert any(a.brand_process_id == "all" and a.date.weekday() == 6 for a in result.roster.assignments)


def test_public_holiday_status_for_closed_process():
    inp = company(("p", d.DAILY_EXCEPT_HOLIDAYS, "g"), allocations=[("a", "p")], holidays=[d.Holiday(DEC(9), "Festival")])
    result, _, _ = run(inp)
    assert result.roster.days[("a", DEC(9))].status in (d.HOLIDAY, d.WEEKLY_OFF)
    assert not [a for a in result.roster.assignments if a.date == DEC(9)]


def test_holiday_staffed_only_to_minimum():
    inp = company(("p", d.ALL_DAYS, "g"), employees=("a", "b", "c"), allocations=[("a", "p"), ("b", "p"), ("c", "p")],
                  holidays=[d.Holiday(DEC(9), "Festival")])
    result, _, _ = run(inp)
    assert len([a for a in result.roster.assignments if a.date == DEC(9)]) == 1


def test_approved_leave_is_honoured_and_pending_is_not_blocking():
    inp = company(("p", d.ALL_DAYS, "g"), employees=("a", "b"), allocations=[("a", "p"), ("b", "p", d.BACKUP, 100)],
                  leaves=[d.Leave("l", "a", "sick", "approved", DEC(9), DEC(10)),
                          d.Leave("m", "a", "planned", "pending", DEC(16), DEC(16))])
    result, _, gaps = run(inp)
    assert gaps == []
    assert result.roster.days[("a", DEC(9))].status == d.LEAVE
    assert {a.employee_id for a in result.roster.assignments if a.date == DEC(9)} == {"b"}


def test_comp_off_leave_and_unavailable_statuses():
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")],
                  leaves=[d.Leave("l", "a", "comp_off", "approved", DEC(9), DEC(9)),
                          d.Leave("m", "a", "unavailable", "approved", DEC(10), DEC(10))])
    result, _, _ = run(inp)
    assert result.roster.days[("a", DEC(9))].status == d.COMP_OFF
    assert result.roster.days[("a", DEC(10))].status == d.UNAVAILABLE


def test_coverage_beats_a_preferred_day_off():
    """The brief's example: a required coverage day outranks a preferred weekly off."""
    inp = company(("p", d.SUNDAYS_HOLIDAYS_OFF, "g"), allocations=[("a", "p")],
                  preferences=[d.Preference("a", "off_weekday", weekday=2, weight=5)])
    result, issues, gaps = run(inp)
    assert gaps == []
    assert result.roster.days[("a", DEC(2))].status == d.WORK
    assert of(issues, "PREFERRED_OFF_MISSED")


def test_preference_honoured_when_coverage_allows():
    inp = company(("p", d.ALL_DAYS, "g"), employees=("a", "b"), allocations=[("a", "p"), ("b", "p")],
                  preferences=[d.Preference("a", "off_date", date=DEC(9), weight=5)])
    result, _, gaps = run(inp)
    assert gaps == []
    assert result.roster.days[("a", DEC(9))].status == d.WEEKLY_OFF


def test_fixed_weekly_off_pattern():
    emp = d.Employee("a", "A", "p", weekly_off_policy="fixed", fixed_off_weekdays=(2,))
    inp = company(("p", d.ALL_DAYS, "g"), employees=(emp,), allocations=[("a", "p")])
    result, _, _ = run(inp)
    offs = [x for (_, x), r in result.roster.days.items() if r.status == d.WEEKLY_OFF]
    assert offs and all(x.weekday() == 2 for x in offs)


def test_rotating_weekly_off_pattern():
    emp = d.Employee("a", "A", "p", weekly_off_policy="rotating", rotation_weekdays=(0, 1))
    inp = company(("p", d.ALL_DAYS, "g"), employees=(emp,), allocations=[("a", "p")])
    result, _, _ = run(inp)
    offs = sorted(x for (_, x), r in result.roster.days.items() if r.status == d.WEEKLY_OFF)
    assert {x.weekday() for x in offs} == {0, 1}
    assert len({x.weekday() for x in offs[:2]}) == 2


def test_different_patterns_on_one_brand():
    a = d.Employee("a", "A", "p", weekly_off_policy="fixed", fixed_off_weekdays=(0,))
    b = d.Employee("b", "B", "p", weekly_off_policy="fixed", fixed_off_weekdays=(3,))
    inp = company(("p", d.ALL_DAYS, "g"), employees=(a, b), allocations=[("a", "p"), ("b", "p")])
    result, _, gaps = run(inp)
    assert gaps == []
    assert all(x.weekday() == 0 for (e, x), r in result.roster.days.items() if e == "a" and r.status == d.WEEKLY_OFF)
    assert all(x.weekday() == 3 for (e, x), r in result.roster.days.items() if e == "b" and r.status == d.WEEKLY_OFF)


def test_overlapping_shifts_produce_a_named_gap_not_a_clash():
    inp = company(("g", d.ALL_DAYS, "g"), ("l", d.ALL_DAYS, "l"),
                  allocations=[("a", "g", d.PRIMARY, 50), ("a", "l", d.PRIMARY, 50)])
    result, issues, gaps = run(inp)
    assert not of(issues, "SHIFT_CLASH")
    assert len(gaps) >= 25
    assert len({a.brand_process_id for a in result.roster.assignments if a.date == DEC(2)}) <= 1


def test_rest_rule_blocks_late_then_early():
    inp = company(("l", d.ALL_DAYS, "l"), ("e", d.ALL_DAYS, "e"), allocations=[("a", "l", d.PRIMARY, 100), ("a", "e", d.PRIMARY, 100)])
    run(inp)  # the helper asserts REST_TOO_SHORT never appears


def test_rest_rule_uses_last_months_shift():
    history = [d.HistoryDay("a", date(2026, 11, 30), d.WORK, ("l",))]
    inp = company(("e", d.ALL_DAYS, "e"), allocations=[("a", "e")], history=history)
    result, _, _ = run(inp)
    assert not [x for x in result.roster.assignments if x.date == DEC(1)]


def test_consecutive_days_carry_over_from_last_month():
    history = [d.HistoryDay("a", date(2026, 11, day), d.WORK, ("g",)) for day in range(25, 31)]
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")], history=history)
    result, _, _ = run(inp)
    assert result.roster.days[("a", DEC(1))].status != d.WORK


def test_stretch_limit_on_cover_days():
    inp = company(("own", d.ALL_DAYS, "g"), ("other", d.ALL_DAYS, "g"), employees=("a", "b"),
                  allocations=[("a", "own", d.PRIMARY, 100), ("b", "other", d.PRIMARY, 100), ("a", "other", d.BACKUP, 25), ("b", "own", d.BACKUP, 25)])
    result, issues, gaps = run(inp)
    assert gaps == []
    assert of(issues, "STRETCH_USED")
    assert not of(issues, "WORKLOAD_EXCEEDED")


def test_too_large_cover_cannot_be_taken():
    inp = company(("own", d.ALL_DAYS, "g"), ("other", d.ALL_DAYS, "g"), employees=("a", "b"),
                  allocations=[("a", "own", d.PRIMARY, 100), ("b", "other", d.PRIMARY, 100), ("a", "other", d.BACKUP, 60)])
    result, _, gaps = run(inp)
    assert gaps  # 160% is over the stretch limit, so nobody can do both
    by_day = result.roster.by_employee_day()
    assert all(sum(a.share for a in items) <= 125 for items in by_day.values())


def test_specific_day_minimum_staff():
    inp = company(("p", d.ALL_DAYS, "g"), employees=("a", "b", "c"),
                  allocations=[("a", "p"), ("b", "p"), ("c", "p", d.BACKUP, 100)],
                  coverage_rules=[d.CoverageRule("p", "date", 3, date=DEC(9))])
    result, _, gaps = run(inp)
    assert gaps == []
    assert {a.employee_id for a in result.roster.assignments if a.date == DEC(9)} == {"a", "b", "c"}


def test_no_allocation_is_flagged():
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[])
    _, issues, gaps = run(inp)
    assert len(gaps) == 31
    assert of(issues, "NO_BACKUP_CONFIGURED")


def test_multi_employee_day_with_one_absent():
    """One of three unavailable: the others keep required coverage."""
    inp = company(("p", d.ALL_DAYS, "g"), employees=("a", "b", "c"), allocations=[("a", "p"), ("b", "p"), ("c", "p")],
                  coverage_rules=[d.CoverageRule("p", "default", 2)],
                  leaves=[d.Leave("l", "a", "planned", "approved", DEC(9), DEC(9))])
    result, _, gaps = run(inp)
    assert gaps == []
    assert {a.employee_id for a in result.roster.assignments if a.date == DEC(9)} == {"b", "c"}


def test_employee_with_no_duties_still_has_a_schedule():
    inp = company(("p", d.ALL_DAYS, "g"), employees=("a", "spare"), allocations=[("a", "p")])
    result, _, _ = run(inp)
    statuses = {r.status for (e, _), r in result.roster.days.items() if e == "spare"}
    assert statuses <= {d.IDLE, d.WEEKLY_OFF}
    assert d.WEEKLY_OFF in statuses


@pytest.mark.parametrize("month", [(2026, 2), (2027, 1), (2026, 11), (2024, 2)])
def test_month_shapes(month):
    inp = company(("p", d.ALL_DAYS, "g"), employees=("a", "b"), allocations=[("a", "p"), ("b", "p")], year=month[0], month=month[1])
    _, _, gaps = run(inp)
    assert gaps == []


def test_sample_month_every_plan_breaks_no_hard_rule():
    inp = sample_input()
    minima = set()
    for plan in plans.PLANS:
        result = plans.generate(inp, plan, time_limit=6, workers=4)
        issues = validate(inp, result.roster)
        assert not [i for i in issues if i.code in NEVER_BROKEN]
        minima.add(sum(result.uncovered.values()))
        m = plans.metrics(inp, result.roster, issues)
        assert m["gap_slots"] == sum(result.uncovered.values())
        assert m["coverage_pct"] > 95
    assert len(minima) == 1  # preferences never trade away coverage


def test_sample_data_matches_the_brief():
    from collections import defaultdict
    inp = sample_input()
    assert len(inp.employees) >= 30
    holders = defaultdict(set)
    bp_brand = {b.id: b.brand_id for b in inp.brand_processes}
    for a in inp.allocations:
        if a.role != d.BACKUP:
            holders[bp_brand[a.brand_process_id]].add(a.employee_id)
    counts = [len(v) for v in holders.values()]
    assert counts.count(1) / len(counts) == pytest.approx(0.8, abs=0.05)
    assert all(c in (1, 2, 3) for c in counts)
    per_process = defaultdict(set)
    for a in inp.allocations:
        if a.role != d.BACKUP:
            per_process[a.brand_process_id].add(a.employee_id)
    assert any(len(v) > 1 for v in per_process.values())  # overlapping process assignments
