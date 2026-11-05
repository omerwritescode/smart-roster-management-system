"""Small hand-built companies for engine tests."""
from __future__ import annotations

from datetime import date

from backend.engine import domain as d
from backend.engine.calendar import month_days

GENERAL = d.Shift("g", "General", 600, 1140)
EARLY = d.Shift("e", "Early", 420, 960)
LATE = d.Shift("l", "Late", 780, 1320)
NEVER_BROKEN = {
    "DAYS_MISSING", "LEAVE_NOT_HONOURED", "ASSIGNED_WHEN_OFF", "NOT_ALLOCATED", "WORKLOAD_EXCEEDED",
    "SHIFT_CLASH", "REST_TOO_SHORT", "WEEKLY_OFF_MISSING", "MAX_CONSECUTIVE_EXCEEDED",
}
COVERAGE = {"NO_AVAILABLE_EMPLOYEE", "INSUFFICIENT_STAFFING"}


def company(*process_specs, employees=("a",), allocations=(), year=2026, month=12, **kwargs) -> d.RosterInput:
    """process_specs: (id, calendar, shift_id) tuples, all on brand "b"; process ids double as process types."""
    bps, procs = [], []
    for spec in process_specs:
        pid, calendar, shift = spec[0], spec[1], spec[2]
        bps.append(d.BrandProcess(id=pid, brand_id=spec[3] if len(spec) > 3 else "b", process_id=pid, shift_id=shift, calendar_type=calendar))
        procs.append(d.Process(pid, pid.upper(), pid.upper()))
    emps = [e if isinstance(e, d.Employee) else d.Employee(id=e, name=e.title(), pod_id="p") for e in employees]
    allocs = [
        d.Allocation(f"al{i}", x[0], x[1], x[2] if len(x) > 2 else d.PRIMARY, x[3] if len(x) > 3 else 100)
        for i, x in enumerate(allocations)
    ]
    brand_ids = sorted({bp.brand_id for bp in bps}) or ["b"]
    return d.RosterInput(
        year=year, month=month, employees=emps, shifts=[GENERAL, EARLY, LATE],
        brands=[d.Brand(b, b.upper(), "p") for b in brand_ids], processes=procs,
        brand_processes=bps, allocations=allocs, **kwargs,
    )


def blank_roster(inp: d.RosterInput, status: str = d.IDLE) -> d.Roster:
    r = d.Roster()
    for e in inp.employees:
        for day in month_days(inp.year, inp.month):
            r.days[(e.id, day)] = d.RosterDay(e.id, day, status)
    return r


def work(roster: d.Roster, inp: d.RosterInput, emp: str, bp_id: str, day: date, share=100, cover=False, shift=None):
    bp = next(b for b in inp.brand_processes if b.id == bp_id)
    roster.days[(emp, day)] = d.RosterDay(emp, day, d.WORK)
    roster.assignments.append(d.Assignment(emp, bp_id, day, shift or bp.shift_id, cover, share))


def codes(issues) -> set[str]:
    return {i.code for i in issues}


def of(issues, code) -> list[d.Issue]:
    return [i for i in issues if i.code == code]
