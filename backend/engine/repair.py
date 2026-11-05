"""Manual edits, roster differences and minimal-change regeneration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from . import domain as d
from .calendar import LEAVE_STATUS, Context
from .plans import PLANS
from .solver import SolveOptions, SolveResult, _make_assignment, solve


@dataclass(frozen=True)
class DayEdit:
    employee_id: str
    date: date
    status: str
    bp_ids: tuple[str, ...] = ()


def apply_edit(inp: d.RosterInput, roster: d.Roster, edit: DayEdit) -> d.Roster:
    """Return a copy of the roster with one employee-day changed. Rules are not checked here."""
    if edit.status not in d.ALL_STATUSES:
        raise ValueError(f"Unknown status: {edit.status}")
    ctx = Context(inp)
    new = roster.copy()
    key = (edit.employee_id, edit.date)
    before = new.days.get(key)
    bp_ids = edit.bp_ids if edit.status == d.WORK else ()
    status = edit.status
    if status == d.WORK and not bp_ids:
        status = d.IDLE
    note = before.note if before else ""
    if status == d.WORK and before is not None and before.status == d.WEEKLY_OFF:
        # Moving a weekly off is fine; working through one earns a comp-off (see below).
        note = d.NOTE_WORKED_WEEKLY_OFF
    elif status != d.WORK and note == d.NOTE_WORKED_WEEKLY_OFF:
        note = ""
    new.days[key] = d.RosterDay(edit.employee_id, edit.date, status, source="manual", locked=True, note=note)
    new.assignments = [a for a in new.assignments if not (a.employee_id == edit.employee_id and a.date == edit.date)]
    for bp_id in bp_ids:
        if bp_id in ctx.bps:
            new.assignments.append(_make_assignment(ctx, edit.employee_id, bp_id, edit.date))
    settle_worked_offs(ctx, new, edit.employee_id, edit.date)
    return new


def settle_worked_offs(ctx: Context, roster: d.Roster, employee_id: str, day: date) -> None:
    """Keep the comp-off note only while the week really is short of a weekly off.

    Swapping an off to another day in the week does not earn a comp-off.
    """
    employee = ctx.employees.get(employee_id)
    if employee is None:
        return
    for monday, days in ctx.weeks():
        if day not in days:
            continue
        need = ctx.week_need(employee, monday, days)
        offs = sum(1 for x in days if (r := roster.days.get((employee_id, x))) and r.status == d.WEEKLY_OFF)
        short = max(0, need.need - offs)
        for x in days:
            r = roster.days.get((employee_id, x))
            if r and r.note == d.NOTE_WORKED_WEEKLY_OFF:
                if short > 0:
                    short -= 1
                else:
                    r.note = ""


def diff(old: d.Roster, new: d.Roster) -> list[dict]:
    """Every employee-day that differs between two rosters."""
    old_map = old.by_employee_day()
    new_map = new.by_employee_day()
    changes = []
    for key in sorted(set(old.days) | set(new.days), key=lambda k: (k[1], k[0])):
        a, b = old.days.get(key), new.days.get(key)
        old_bps = sorted(x.brand_process_id for x in old_map.get(key, []))
        new_bps = sorted(x.brand_process_id for x in new_map.get(key, []))
        if (a.status if a else None) == (b.status if b else None) and old_bps == new_bps:
            continue
        changes.append({
            "employee_id": key[0], "date": key[1].isoformat(),
            "from_status": a.status if a else None, "to_status": b.status if b else None,
            "from_processes": old_bps, "to_processes": new_bps,
        })
    return changes


def repair(
    inp: d.RosterInput,
    base: d.Roster,
    change_from: date,
    plan: str = "coverage_first",
    time_limit: float | None = None,
    workers: int | None = None,
) -> SolveResult:
    """Re-solve from `change_from` onwards, keeping as much of `base` as possible.

    Locked: everything before `change_from`, and later manual edits, because a person
    chose those. A later manual edit is released only when newly approved leave makes
    it impossible for that person to work the day.
    """
    ctx = Context(inp)
    by_day = base.by_employee_day()
    locks: dict[tuple[str, date], tuple[str, tuple[str, ...], str]] = {}
    for key, rec in base.days.items():
        emp_id, day = key
        if emp_id not in ctx.employees or not (ctx.first_day <= day <= ctx.last_day):
            continue
        if day < change_from:
            pass
        elif not rec.locked or key in ctx.blocked:
            continue
        bps = tuple(a.brand_process_id for a in by_day.get(key, []) if a.brand_process_id in ctx.bps)
        status = rec.status
        if status == d.WORK and not bps:
            status = d.IDLE
        locks[key] = (status, bps, rec.note)
    options = SolveOptions(
        weights=PLANS[plan]["weights"], locks=locks, baseline=base, time_limit=time_limit, workers=workers,
    )
    result = solve(inp, options)
    for key, rec in result.roster.days.items():
        if key in locks:
            continue
        old = base.days.get(key)
        same = old is not None and old.status == rec.status and (
            sorted(a.brand_process_id for a in by_day.get(key, []))
            == sorted(a.brand_process_id for a in result.roster.assignments if (a.employee_id, a.date) == key)
        )
        rec.source = old.source if same and old else "repair"
    return result


def absence_preview(inp: d.RosterInput, roster: d.Roster, employee_id: str, start: date, end: date, leave_type: str) -> d.Roster:
    """The roster as it would stand if a person were away, with nothing else changed."""
    ctx = Context(inp)
    new = roster.copy()
    status = LEAVE_STATUS[leave_type]
    new.assignments = [a for a in new.assignments if not (a.employee_id == employee_id and start <= a.date <= end)]
    for day in ctx.days:
        if start <= day <= end and (employee_id, day) in new.days:
            new.days[(employee_id, day)] = d.RosterDay(employee_id, day, status, source="manual")
    return new
