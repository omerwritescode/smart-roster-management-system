"""Handling change: manual edits, repair, backup recommendations and the brief's scenarios."""
from datetime import date

from backend.engine import domain as d
from backend.engine.advisor import employee_impact, recommend
from backend.engine.repair import DayEdit, absence_preview, apply_edit, diff, repair
from backend.engine.solver import SolveOptions, solve
from backend.engine.validator import validate
from backend.engine import plans

from .factory import COVERAGE, NEVER_BROKEN, blank_roster, company, of, work
from .sample import sample_input

DEC = lambda day: date(2026, 12, day)  # noqa: E731
FAST = dict(time_limit=4, workers=2)


def two_person():
    return company(("p", d.ALL_DAYS, "g"), employees=("a", "b"), allocations=[("a", "p"), ("b", "p", d.BACKUP, 100)])


def test_manual_edit_goes_through_the_same_validator():
    inp = two_person()
    base = solve(inp, SolveOptions(**FAST)).roster
    day = next(x for (e, x), r in base.days.items() if e == "a" and r.status == d.WORK)
    edited = apply_edit(inp, base, DayEdit("a", day, d.WEEKLY_OFF))
    issues = validate(inp, edited)
    assert any(i.category == "coverage" and i.date == day for i in issues)
    assert edited.days[("a", day)].source == "manual" and edited.days[("a", day)].locked


def test_working_through_a_weekly_off_flags_and_earns():
    inp = two_person()
    base = solve(inp, SolveOptions(**FAST)).roster
    day = next(x for (e, x), r in base.days.items() if e == "a" and r.status == d.WEEKLY_OFF)
    edited = apply_edit(inp, base, DayEdit("a", day, d.WORK, ("p",)))
    assert edited.days[("a", day)].note == d.NOTE_WORKED_WEEKLY_OFF
    assert of(validate(inp, edited), "WEEKLY_OFF_MISSING")


def test_moving_a_weekly_off_inside_the_week_earns_nothing():
    inp = two_person()
    base = solve(inp, SolveOptions(**FAST)).roster
    day = next(x for (e, x), r in sorted(base.days.items(), key=lambda kv: kv[0][1])
               if e == "a" and r.status == d.WEEKLY_OFF and x >= DEC(7))
    other = next(x for x in [DEC(7), DEC(8), DEC(9), DEC(10), DEC(11), DEC(12), DEC(13)] if x != day and base.days[("a", x)].status != d.WEEKLY_OFF) \
        if DEC(7) <= day <= DEC(13) else None
    if other is None:
        return
    edited = apply_edit(inp, base, DayEdit("a", day, d.WORK, ("p",)))
    edited = apply_edit(inp, edited, DayEdit("a", other, d.WEEKLY_OFF))
    assert edited.days[("a", day)].note == ""


def test_diff_lists_only_changed_days():
    inp = two_person()
    base = solve(inp, SolveOptions(**FAST)).roster
    assert diff(base, base.copy()) == []
    day = next(x for (e, x), r in base.days.items() if e == "a" and r.status == d.WORK)
    edited = apply_edit(inp, base, DayEdit("a", day, d.WEEKLY_OFF))
    changes = diff(base, edited)
    assert len(changes) == 1 and changes[0]["to_status"] == d.WEEKLY_OFF


def test_repair_covers_a_new_absence_with_few_changes():
    inp = two_person()
    base = solve(inp, SolveOptions(**FAST)).roster
    day = next(x for (e, x), r in sorted(base.days.items(), key=lambda kv: kv[0][1])
               if e == "a" and r.status == d.WORK and x >= DEC(15))
    changed = company(("p", d.ALL_DAYS, "g"), employees=("a", "b"), allocations=[("a", "p"), ("b", "p", d.BACKUP, 100)],
                      leaves=[d.Leave("n", "a", "sick", "approved", day, day)])
    result = repair(changed, base, DEC(15), **FAST)
    assert result.roster.days[("a", day)].status == d.LEAVE
    assert {a.employee_id for a in result.roster.assignments if a.date == day} == {"b"}
    changes = diff(base, result.roster)
    assert all(c["date"] >= DEC(15).isoformat() for c in changes)
    assert len(changes) <= 4  # the absence, its cover, and at most one off moved


def test_repair_keeps_manual_edits_after_the_change_date():
    inp = two_person()
    base = solve(inp, SolveOptions(**FAST)).roster
    day = next(x for (e, x), r in sorted(base.days.items(), key=lambda kv: kv[0][1])
               if e == "a" and r.status == d.WORK and x >= DEC(20))
    edited = apply_edit(inp, base, DayEdit("a", day, d.IDLE))
    result = repair(inp, edited, DEC(10), **FAST)
    assert result.roster.days[("a", day)].status == d.IDLE
    assert result.roster.days[("a", day)].locked


def test_repair_releases_a_manual_edit_when_new_leave_blocks_it():
    inp = two_person()
    base = solve(inp, SolveOptions(**FAST)).roster
    day = next(x for (e, x), r in sorted(base.days.items(), key=lambda kv: kv[0][1])
               if e == "a" and r.status == d.WORK and x >= DEC(20))
    edited = apply_edit(inp, base, DayEdit("a", day, d.WORK, ("p",)))
    changed = company(("p", d.ALL_DAYS, "g"), employees=("a", "b"), allocations=[("a", "p"), ("b", "p", d.BACKUP, 100)],
                      leaves=[d.Leave("n", "a", "sick", "approved", day, day)])
    result = repair(changed, edited, DEC(10), **FAST)
    assert result.roster.days[("a", day)].status == d.LEAVE


def test_repair_reacts_to_a_new_brand_requirement():
    """A brand opening on a day it used to close is picked up without rebuilding everything."""
    inp = company(("p", d.SUNDAYS_HOLIDAYS_OFF, "g"), allocations=[("a", "p")])
    base = solve(inp, SolveOptions(**FAST)).roster
    changed = company(("p", d.SUNDAYS_HOLIDAYS_OFF, "g"), employees=("a", "b"),
                      allocations=[("a", "p"), ("b", "p", d.BACKUP, 100)],
                      coverage_rules=[d.CoverageRule("p", "date", 1, date=DEC(20))])
    result = repair(changed, _add_blank(changed, base), DEC(15), **FAST)
    assert any(a.date == DEC(20) and a.brand_process_id == "p" for a in result.roster.assignments)
    assert not [i for i in validate(changed, result.roster) if i.code in COVERAGE and i.date >= DEC(15)]


def _add_blank(inp, roster):
    new = roster.copy()
    for key, rec in blank_roster(inp).days.items():
        new.days.setdefault(key, rec)
    return new


def test_recommend_ranks_and_tests_every_option():
    inp = company(("p", d.ALL_DAYS, "g"), ("q", d.ALL_DAYS, "g", "c"), employees=("a", "b", "c"),
                  allocations=[("a", "p"), ("b", "p", d.BACKUP, 100), ("c", "q", d.PRIMARY, 100)])
    # q is the same kind of work as p, at another brand
    inp.brand_processes[1] = d.BrandProcess("q", "c", "p", "g", d.ALL_DAYS)
    roster = blank_roster(inp)
    work(roster, inp, "c", "q", DEC(9))
    result = recommend(inp, roster, "p", DEC(9))
    names = [o["employee_id"] for o in result["options"]]
    assert set(names[:2]) == {"a", "b"}  # the two people already allocated come first
    assert all(o["valid"] and o["fixes_gap"] for o in result["options"][:2])
    trained = next(o for o in result["options"] if o["employee_id"] == "c")
    assert trained["tier"] == 2 and trained["needs_allocation"]


def test_recommend_excludes_people_on_leave_and_explains_rule_breaks():
    inp = company(("p", d.ALL_DAYS, "g"), employees=("a", "b", "c"), allocations=[("a", "p"), ("b", "p", d.BACKUP, 100), ("c", "p", d.BACKUP, 100)],
                  leaves=[d.Leave("n", "b", "planned", "approved", DEC(9), DEC(9))])
    roster = blank_roster(inp)
    roster.days[("b", DEC(9))].status = d.LEAVE
    for i in range(3, 9):
        work(roster, inp, "c", "p", DEC(i))
    result = recommend(inp, roster, "p", DEC(9))
    ids = [o["employee_id"] for o in result["options"]]
    assert "b" not in ids
    c = next(o for o in result["options"] if o["employee_id"] == "c")
    assert not c["valid"] and any("consecutive" in m for m in c["new_blockers"])


def test_recommend_offers_weekly_off_swap():
    inp = company(("p", d.SUNDAYS_HOLIDAYS_OFF, "g"), allocations=[("a", "p")],
                  coverage_rules=[d.CoverageRule("p", "date", 1, date=DEC(13))])
    roster = solve(inp, SolveOptions(**FAST)).roster
    for x in (DEC(9),):
        roster = apply_edit(inp, roster, DayEdit("a", x, d.WEEKLY_OFF))
    roster = apply_edit(inp, roster, DayEdit("a", DEC(13), d.WEEKLY_OFF))
    result = recommend(inp, roster, "p", DEC(13))
    assert isinstance(result["swaps"], list)


# ---------------------------------------------------------------- the brief's scenarios
def _sample():
    inp = sample_input()
    return inp, plans.generate(inp, "coverage_first", time_limit=8, workers=4).roster


def test_scenario_single_employee_brand_becomes_unavailable():
    inp, roster = _sample()
    target = next(
        x for (e, x), r in sorted(roster.days.items(), key=lambda kv: kv[0][1])
        if e == "emp-karan" and r.status == d.WORK and x >= DEC(9)
    )
    preview = absence_preview(inp, roster, "emp-karan", target, target, "unavailable")
    impact = employee_impact(inp, roster, preview)
    assert "Haldi House" in impact["brands_affected"]
    gap = next(i for i in impact["introduced"] if i.category == "coverage" and i.brand_process_id == "haldi-cs")
    assert gap.date == target

    changed = d.RosterInput(**{**inp.__dict__, "leaves": [
        *inp.leaves, d.Leave("x", "emp-karan", "unavailable", "approved", target, target)]})
    advice = recommend(changed, preview, "haldi-cs", target)
    valid = [o for o in advice["options"] if o["valid"]]
    assert valid, advice["summary"]
    edited = apply_edit(changed, preview, DayEdit(
        valid[0]["employee_id"], target, d.WORK, tuple(valid[0]["edit"]["bp_ids"])))
    assert not [i for i in validate(changed, edited) if i.brand_process_id == "haldi-cs" and i.date == target and i.category == "coverage"]


def test_scenario_one_of_three_unavailable_shared_process_holds():
    """Ember Candles CS is shared by two of its three people. Losing one keeps the minimum."""
    inp, roster = _sample()
    target = next(
        x for (e, x), r in sorted(roster.days.items(), key=lambda kv: kv[0][1])
        if e == "emp-riya" and r.status == d.WORK and x >= DEC(7) and x.weekday() != 5
        and roster.days[("emp-kabir", x)].status == d.WORK
    )
    preview = absence_preview(inp, roster, "emp-riya", target, target, "unavailable")
    impact = employee_impact(inp, roster, preview)
    gaps = [i for i in impact["introduced"] if i.category == "coverage"]
    assert "ember-cs" not in {i.brand_process_id for i in gaps}   # Kabir keeps CS at its minimum
    assert "ember-ndr" in {i.brand_process_id for i in gaps}      # NDR was only Riya's


def test_scenario_regeneration_after_approved_leave():
    inp, roster = _sample()
    target = next(
        x for (e, x), r in sorted(roster.days.items(), key=lambda kv: kv[0][1])
        if e == "emp-meera" and r.status in (d.WORK, d.IDLE) and x >= DEC(9)
    )
    changed = d.RosterInput(**{**inp.__dict__, "leaves": [
        *inp.leaves, d.Leave("x", "emp-priya", "planned", "approved", DEC(17), DEC(18))]})
    result = repair(changed, roster, DEC(17), time_limit=8, workers=4)
    issues = validate(changed, result.roster)
    assert not [i for i in issues if i.code in NEVER_BROKEN and i.date and i.date >= DEC(17)]
    assert result.roster.days[("emp-priya", DEC(17))].status == d.LEAVE
    changes = diff(roster, result.roster)
    assert all(c["date"] >= "2026-12-17" for c in changes)
    assert len(changes) < 60  # a small part of the 1,054 employee-days
    assert target


def test_frozen_past_days_are_not_marked_as_manual_edits():
    """Otherwise a second regeneration would treat old solver days as a person's choices."""
    inp = two_person()
    base = solve(inp, SolveOptions(**FAST)).roster
    result = repair(inp, base, DEC(15), **FAST)
    assert not [r for (_, x), r in result.roster.days.items() if x < DEC(15) and r.locked]
    again = repair(inp, result.roster, DEC(5), **FAST)
    assert not [r for r in again.roster.days.values() if r.locked]
