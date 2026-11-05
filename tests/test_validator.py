"""Each validator rule, checked against rosters built by hand with no solver involved."""
from datetime import date, timedelta

from backend.engine import domain as d
from backend.engine.calendar import Context
from backend.engine.validator import comp_off_entitlements, validate

from .factory import blank_roster, codes, company, of, work

DEC = lambda day: date(2026, 12, day)  # noqa: E731


def test_calendar_types_on_sunday_and_holiday():
    inp = company(("all", d.ALL_DAYS, "g"), ("daily", d.DAILY_EXCEPT_HOLIDAYS, "g"), ("sh", d.SUNDAYS_HOLIDAYS_OFF, "g"),
                  holidays=[d.Holiday(DEC(25), "Christmas")])
    ctx = Context(inp)
    sunday, holiday, monday = DEC(6), DEC(25), DEC(7)
    assert [ctx.required("all", x) for x in (sunday, holiday, monday)] == [1, 1, 1]
    assert [ctx.required("daily", x) for x in (sunday, holiday, monday)] == [1, 0, 1]
    assert [ctx.required("sh", x) for x in (sunday, holiday, monday)] == [0, 0, 1]


def test_most_specific_coverage_rule_wins():
    inp = company(("p", d.DAILY_EXCEPT_HOLIDAYS, "g"), coverage_rules=[
        d.CoverageRule("p", "default", 2),
        d.CoverageRule("p", "weekday", 3, weekday=5),
        d.CoverageRule("p", "date", 4, date=DEC(5)),   # a Saturday
        d.CoverageRule("p", "date", 1, date=DEC(25)),  # opens on a holiday
        d.CoverageRule("p", "date", 0, date=DEC(8)),   # closes on a normal day
    ], holidays=[d.Holiday(DEC(25), "Christmas")])
    ctx = Context(inp)
    assert ctx.required("p", DEC(7)) == 2
    assert ctx.required("p", DEC(12)) == 3
    assert ctx.required("p", DEC(5)) == 4
    assert ctx.required("p", DEC(25)) == 1
    assert ctx.required("p", DEC(8)) == 0


def test_custom_calendar_mask():
    inp = company(("p", d.CUSTOM, "g"))
    inp.brand_processes[0] = d.BrandProcess("p", "b", "p", "g", d.CUSTOM, (5,), True)
    ctx = Context(inp)
    assert ctx.required("p", DEC(5)) == 1
    assert ctx.required("p", DEC(7)) == 0


def test_gap_with_nobody_available_names_the_cause():
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")])
    roster = blank_roster(inp, d.WEEKLY_OFF)
    gaps = [i for i in validate(inp, roster) if i.code == "NO_AVAILABLE_EMPLOYEE" and i.date == DEC(2)]
    assert len(gaps) == 1
    assert gaps[0].severity == d.BLOCKER
    assert gaps[0].facts["causes"] == ["weekly_off"]
    assert "A (primary) is on weekly off" in gaps[0].message


def test_insufficient_staffing_when_partly_staffed():
    inp = company(("p", d.ALL_DAYS, "g"), employees=("a", "b"), allocations=[("a", "p"), ("b", "p")],
                  coverage_rules=[d.CoverageRule("p", "default", 2)])
    roster = blank_roster(inp)
    work(roster, inp, "a", "p", DEC(2))
    gaps = [i for i in validate(inp, roster) if i.date == DEC(2) and i.category == "coverage"]
    assert gaps[0].code == "INSUFFICIENT_STAFFING"
    assert gaps[0].facts["short_by"] == 1


def test_closed_day_needs_no_coverage():
    inp = company(("p", d.SUNDAYS_HOLIDAYS_OFF, "g"), allocations=[("a", "p")])
    roster = blank_roster(inp)
    assert not [i for i in validate(inp, roster) if i.category == "coverage" and i.date == DEC(6)]


def test_working_on_approved_leave_is_blocked():
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")],
                  leaves=[d.Leave("l", "a", "planned", "approved", DEC(2), DEC(2))])
    roster = blank_roster(inp)
    work(roster, inp, "a", "p", DEC(2))
    assert of(validate(inp, roster), "LEAVE_NOT_HONOURED")


def test_pending_and_rejected_leave_do_not_block():
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")],
                  leaves=[d.Leave("l", "a", "planned", "pending", DEC(2), DEC(2)),
                          d.Leave("m", "a", "planned", "rejected", DEC(3), DEC(3))])
    roster = blank_roster(inp)
    work(roster, inp, "a", "p", DEC(2))
    work(roster, inp, "a", "p", DEC(3))
    issues = validate(inp, roster)
    assert not of(issues, "LEAVE_NOT_HONOURED")
    assert [i.date for i in of(issues, "PENDING_LEAVE_CLASH")] == [DEC(2)]


def test_assignment_without_allocation_is_blocked():
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[])
    roster = blank_roster(inp)
    work(roster, inp, "a", "p", DEC(2))
    assert of(validate(inp, roster), "NOT_ALLOCATED")


def test_allocation_dates_are_respected():
    inp = company(("p", d.ALL_DAYS, "g"))
    inp.allocations = [d.Allocation("x", "a", "p", d.PRIMARY, 100, DEC(10), DEC(20))]
    roster = blank_roster(inp)
    work(roster, inp, "a", "p", DEC(5))
    work(roster, inp, "a", "p", DEC(15))
    assert [i.date for i in of(validate(inp, roster), "NOT_ALLOCATED")] == [DEC(5)]


def test_workload_limits():
    inp = company(("p", d.ALL_DAYS, "g"), ("q", d.ALL_DAYS, "g"), allocations=[("a", "p"), ("a", "q", d.BACKUP, 25)])
    roster = blank_roster(inp)
    work(roster, inp, "a", "p", DEC(2), share=100)
    work(roster, inp, "a", "q", DEC(2), share=25, cover=True)
    issues = validate(inp, roster)
    assert of(issues, "STRETCH_USED") and not of(issues, "WORKLOAD_EXCEEDED")
    work(roster, inp, "a", "q", DEC(3), share=60, cover=False)
    work(roster, inp, "a", "p", DEC(3), share=60)
    assert [i.date for i in of(validate(inp, roster), "WORKLOAD_EXCEEDED")] == [DEC(3)]
    work(roster, inp, "a", "q", DEC(4), share=40, cover=True)
    work(roster, inp, "a", "p", DEC(4), share=100)
    assert DEC(4) in [i.date for i in of(validate(inp, roster), "WORKLOAD_EXCEEDED")]


def test_overlapping_shifts_clash_but_same_shift_does_not():
    inp = company(("p", d.ALL_DAYS, "g"), ("q", d.ALL_DAYS, "l"), ("r", d.ALL_DAYS, "g"),
                  allocations=[("a", "p", d.PRIMARY, 50), ("a", "q", d.PRIMARY, 50), ("a", "r", d.PRIMARY, 50)])
    roster = blank_roster(inp)
    work(roster, inp, "a", "p", DEC(2), share=50)
    work(roster, inp, "a", "r", DEC(2), share=50)
    assert not of(validate(inp, roster), "SHIFT_CLASH")
    work(roster, inp, "a", "p", DEC(3), share=50)
    work(roster, inp, "a", "q", DEC(3), share=50)
    assert [i.date for i in of(validate(inp, roster), "SHIFT_CLASH")] == [DEC(3)]


def test_late_then_early_has_too_little_rest():
    inp = company(("l", d.ALL_DAYS, "l"), ("e", d.ALL_DAYS, "e"), allocations=[("a", "l"), ("a", "e")])
    roster = blank_roster(inp)
    work(roster, inp, "a", "l", DEC(2))
    work(roster, inp, "a", "e", DEC(3))
    issue = of(validate(inp, roster), "REST_TOO_SHORT")[0]
    assert issue.date == DEC(3) and issue.facts["rest_minutes"] == 540
    roster2 = blank_roster(inp)
    work(roster2, inp, "a", "e", DEC(2))
    work(roster2, inp, "a", "l", DEC(3))
    assert not of(validate(inp, roster2), "REST_TOO_SHORT")


def test_rest_check_uses_last_month():
    inp = company(("e", d.ALL_DAYS, "e"), allocations=[("a", "e")],
                  history=[d.HistoryDay("a", DEC(1) - timedelta(days=1), d.WORK, ("l",))])
    roster = blank_roster(inp)
    work(roster, inp, "a", "e", DEC(1))
    assert of(validate(inp, roster), "REST_TOO_SHORT")


def test_week_without_off_is_blocked_and_week_with_off_is_fine():
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")])
    roster = blank_roster(inp, d.WORK)
    missing = of(validate(inp, roster), "WEEKLY_OFF_MISSING")
    # 1-6 Dec (opening part-week of 6 days) and three full weeks. 28-31 Dec can take its off in January.
    assert sorted(i.facts["week_of"] for i in missing) == ["2026-11-30", "2026-12-07", "2026-12-14", "2026-12-21"]
    roster.days[("a", DEC(6))].status = d.WEEKLY_OFF
    assert "2026-11-30" not in {i.facts["week_of"] for i in of(validate(inp, roster), "WEEKLY_OFF_MISSING")}


def test_off_taken_last_month_counts_towards_the_week():
    history = [d.HistoryDay("a", date(2026, 11, 30), d.WEEKLY_OFF)]
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")], history=history)
    roster = blank_roster(inp, d.WORK)
    assert "2026-11-30" not in {i.facts["week_of"] for i in of(validate(inp, roster), "WEEKLY_OFF_MISSING")}


def test_week_entirely_on_leave_needs_no_off():
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")],
                  leaves=[d.Leave("l", "a", "planned", "approved", DEC(7), DEC(13))])
    roster = blank_roster(inp)
    for i in range(7, 14):
        roster.days[("a", DEC(i))].status = d.LEAVE
    assert "2026-12-07" not in {i.facts["week_of"] for i in of(validate(inp, roster), "WEEKLY_OFF_MISSING")}


def test_fixed_pattern_change_warns():
    emp = d.Employee("a", "A", "p", weekly_off_policy="fixed", fixed_off_weekdays=(6,))
    inp = company(("p", d.ALL_DAYS, "g"), employees=(emp,), allocations=[("a", "p")])
    roster = blank_roster(inp)
    roster.days[("a", DEC(9))].status = d.WEEKLY_OFF  # a Wednesday
    assert of(validate(inp, roster), "WEEKLY_OFF_PATTERN")


def test_consecutive_days_limit_and_history():
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")])
    roster = blank_roster(inp)
    for i in range(2, 9):
        work(roster, inp, "a", "p", DEC(i))
    assert of(validate(inp, roster), "MAX_CONSECUTIVE_EXCEEDED")[0].date == DEC(8)

    history = [d.HistoryDay("a", date(2026, 11, day), d.WORK, ("g",)) for day in range(26, 31)]
    inp2 = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")], history=history)
    roster2 = blank_roster(inp2)
    work(roster2, inp2, "a", "p", DEC(1))
    assert not of(validate(inp2, roster2), "MAX_CONSECUTIVE_EXCEEDED")
    work(roster2, inp2, "a", "p", DEC(2))
    assert of(validate(inp2, roster2), "MAX_CONSECUTIVE_EXCEEDED")[0].date == DEC(2)


def test_one_absence_across_two_brands():
    inp = company(("p", d.ALL_DAYS, "g", "b1"), ("q", d.ALL_DAYS, "g", "b2"),
                  allocations=[("a", "p", d.PRIMARY, 50), ("a", "q", d.PRIMARY, 50)],
                  leaves=[d.Leave("l", "a", "planned", "approved", DEC(2), DEC(2))])
    roster = blank_roster(inp)
    roster.days[("a", DEC(2))].status = d.LEAVE
    impact = [i for i in validate(inp, roster) if i.code == "MULTI_BRAND_IMPACT" and i.date == DEC(2)]
    assert len(impact) == 1 and impact[0].facts["brands"] == ["B1", "B2"]


def test_no_backup_flag_and_overallocation():
    inp = company(("p", d.ALL_DAYS, "g"), ("q", d.ALL_DAYS, "g"), allocations=[("a", "p", d.PRIMARY, 80), ("a", "q", d.PRIMARY, 80)])
    issues = validate(inp, blank_roster(inp))
    assert of(issues, "NO_BACKUP_CONFIGURED")
    assert of(issues, "OVERALLOCATED")


def test_preferences_only_warn():
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")],
                  preferences=[d.Preference("a", "off_date", date=DEC(9), weight=5),
                               d.Preference("a", "off_weekday", weekday=6),
                               d.Preference("a", "avoid_shift", shift_id="g")])
    roster = blank_roster(inp)
    work(roster, inp, "a", "p", DEC(9))
    work(roster, inp, "a", "p", DEC(13))
    issues = validate(inp, roster)
    missed = of(issues, "PREFERRED_OFF_MISSED")
    assert {i.date for i in missed} == {DEC(9), DEC(13)}
    assert all(i.severity == d.WARNING for i in missed + of(issues, "AVOIDED_SHIFT_USED"))
    assert of(issues, "AVOIDED_SHIFT_USED")


def test_fairness_warning():
    inp = company(("p", d.ALL_DAYS, "g"), ("q", d.ALL_DAYS, "g"), employees=("a", "b"), allocations=[("a", "p"), ("b", "q")])
    roster = blank_roster(inp)
    for sunday in (6, 13, 20, 27):
        work(roster, inp, "a", "p", DEC(sunday))
    issue = of(validate(inp, roster), "SUNDAY_HOLIDAY_IMBALANCE")[0]
    assert (issue.facts["low"], issue.facts["high"]) == (0, 4)


def test_comp_off_entitlements():
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")], holidays=[d.Holiday(DEC(25), "Christmas")])
    roster = blank_roster(inp)
    work(roster, inp, "a", "p", DEC(25))
    work(roster, inp, "a", "p", DEC(9))
    roster.days[("a", DEC(9))].note = d.NOTE_WORKED_WEEKLY_OFF
    earned = comp_off_entitlements(inp, roster)
    assert ("a", DEC(25), "Worked Christmas") in earned
    assert ("a", DEC(9), "Worked a weekly off") in earned
    assert len(earned) == 2


def test_issue_keys_are_stable():
    inp = company(("p", d.ALL_DAYS, "g"), allocations=[("a", "p")])
    roster = blank_roster(inp)
    assert [i.key for i in validate(inp, roster)] == [i.key for i in validate(inp, roster)]
    assert codes(validate(inp, roster))
