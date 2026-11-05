"""Backup recommendations. Each option is tested in the validator before it is shown."""
from __future__ import annotations

from dataclasses import replace
from datetime import date

from . import domain as d
from .calendar import Context, shifts_overlap
from .repair import DayEdit, apply_edit
from .validator import compare, fmt, validate

TEMP_COVER_SHARE = 25


def _tier(ctx: Context, emp_id: str, bp: d.BrandProcess, day: date) -> tuple[int, str]:
    alloc = ctx.allocation_for(emp_id, bp.id, day)
    if alloc is not None:
        return 1, f"Already allocated as {alloc.role}"
    for a in ctx.employee_allocations(emp_id, day):
        other = ctx.bps[a.brand_process_id]
        if other.process_id == bp.process_id and a.role != d.BACKUP:
            return 2, f"Does {ctx.processes[bp.process_id].code} on {ctx.brands[other.brand_id].name}; needs adding as backup"
    return 3, "Not trained on this process; needs adding as backup"


def recommend(inp: d.RosterInput, roster: d.Roster, bp_id: str, day: date, limit: int = 8) -> dict:
    """Rank who can cover a process on a day, and test each option in the validator."""
    ctx = Context(inp)
    bp = ctx.bps[bp_id]
    required = ctx.required(bp_id, day)
    by_emp_day = roster.by_employee_day()
    staffed = {a.employee_id for a in by_emp_day_all(by_emp_day, bp_id, day)}
    before = validate(inp, roster)
    gap_key = next((i.key for i in before if i.category == "coverage" and i.brand_process_id == bp_id and i.date == day), None)
    cover_counts: dict[str, int] = {}
    for a in roster.assignments:
        if a.is_cover:
            cover_counts[a.employee_id] = cover_counts.get(a.employee_id, 0) + 1
    target_shift = ctx.shifts[bp.shift_id]
    brand = ctx.brands.get(bp.brand_id)

    options = []
    for e in ctx.employees.values():
        if e.id in staffed or (e.id, day) in ctx.blocked:
            continue
        tier, why = _tier(ctx, e.id, bp, day)
        if tier == 3 and not (e.title == "Pod Lead" and brand and e.pod_id == brand.pod_id):
            continue
        rec = roster.days.get((e.id, day))
        status = rec.status if rec else d.IDLE
        todays = by_emp_day.get((e.id, day), [])
        current_load = sum(a.share for a in todays)
        trial_inp = inp
        if tier > 1:
            trial_inp = replace(inp, allocations=[*inp.allocations, d.Allocation(
                f"trial-{e.id}", e.id, bp_id, d.BACKUP, TEMP_COVER_SHARE, day, day)])
        trial = apply_edit(trial_inp, roster, DayEdit(
            e.id, day, d.WORK, tuple(a.brand_process_id for a in todays) + (bp_id,)))
        after = validate(trial_inp, trial)
        changes = compare(before, after)
        new_blockers = [i for i in changes["introduced"] if i.severity == d.BLOCKER]
        new_warnings = [i for i in changes["introduced"] if i.severity == d.WARNING]
        fixes_gap = gap_key is not None and gap_key in {i.key for i in changes["resolved"]}
        clashes = any(
            shifts_overlap(ctx.shifts[a.shift_id], target_shift) for a in todays if a.shift_id in ctx.shifts
        )
        alloc = ctx.allocation_for(e.id, bp_id, day)
        added = alloc.share if alloc else TEMP_COVER_SHARE
        same_pod = bool(brand and e.pod_id == brand.pod_id)
        notes = [why]
        if status == d.WEEKLY_OFF:
            notes.append("Would work through their weekly off and earn a comp-off")
        if status == d.HOLIDAY:
            notes.append("Would work a holiday and earn a comp-off")
        if clashes:
            notes.append("Shift overlaps their other work that day")
        if not same_pod:
            notes.append("From another pod")
        spare = max(0, d.FULL_DAY - current_load)
        rank = (
            0 if not new_blockers else 1,
            tier,
            0 if status in (d.IDLE, d.WORK) else 1,
            0 if current_load + added <= d.FULL_DAY else 1,
            0 if same_pod else 1,
            cover_counts.get(e.id, 0),
            -spare,
            e.name,
        )
        options.append((rank, {
            "employee_id": e.id, "name": e.name, "title": e.title, "pod_id": e.pod_id,
            "tier": tier, "status": status, "current_load": current_load, "load_after": current_load + added,
            "spare_capacity": spare, "same_pod": same_pod, "cover_days_this_month": cover_counts.get(e.id, 0),
            "needs_allocation": tier > 1, "fixes_gap": fixes_gap, "valid": not new_blockers and fixes_gap,
            "new_blockers": [i.message for i in new_blockers], "new_warnings": [i.message for i in new_warnings],
            "notes": notes,
            "edit": {"employee_id": e.id, "date": day.isoformat(), "status": d.WORK,
                     "bp_ids": [a.brand_process_id for a in todays] + [bp_id],
                     "add_backup_allocation": bp_id if tier > 1 else None},
        }))
    options.sort(key=lambda x: x[0])
    ranked = [o for _, o in options][:limit]
    return {
        "process": ctx.bp_label(bp_id), "brand_process_id": bp_id, "date": day.isoformat(),
        "required": required, "staffed": len(staffed),
        "options": ranked,
        "swaps": _weekly_off_swaps(ctx, inp, roster, bp_id, day, before, gap_key),
        "summary": _summary(ctx, bp_id, day, ranked),
    }


def by_emp_day_all(by_emp_day, bp_id: str, day: date) -> list[d.Assignment]:
    return [a for (_, x), items in by_emp_day.items() if x == day for a in items if a.brand_process_id == bp_id]


def _weekly_off_swaps(ctx, inp, roster, bp_id, day, before, gap_key) -> list[dict]:
    """A regular employee off on the gap day may be able to take a different day off."""
    swaps = []
    by_emp_day = roster.by_employee_day()
    for a in ctx.process_allocations(bp_id, day):
        rec = roster.days.get((a.employee_id, day))
        if a.role == d.BACKUP or rec is None or rec.status != d.WEEKLY_OFF:
            continue
        e = ctx.employees[a.employee_id]
        for monday, days in ctx.weeks():
            if day not in days:
                continue
            for other in days:
                if other == day or (e.id, other) in ctx.blocked:
                    continue
                other_rec = roster.days.get((e.id, other))
                if other_rec is None or other_rec.status == d.WEEKLY_OFF:
                    continue
                duties = [x.brand_process_id for x in ctx.employee_allocations(e.id, day)
                          if x.role != d.BACKUP and ctx.required(x.brand_process_id, day) > 0]
                trial = apply_edit(inp, roster, DayEdit(e.id, day, d.WORK, tuple(duties)))
                trial = apply_edit(inp, trial, DayEdit(e.id, other, d.WEEKLY_OFF))
                after = validate(inp, trial)
                changes = compare(before, after)
                new_blockers = [i for i in changes["introduced"] if i.severity == d.BLOCKER]
                if not new_blockers and gap_key in {i.key for i in changes["resolved"]}:
                    swaps.append({
                        "employee_id": e.id, "name": e.name, "from_date": day.isoformat(), "to_date": other.isoformat(),
                        "description": f"Move {e.name}'s weekly off from {fmt(day)} to {fmt(other)}",
                        "new_warnings": [i.message for i in changes["introduced"] if i.severity == d.WARNING],
                        "edits": [
                            {"employee_id": e.id, "date": day.isoformat(), "status": d.WORK, "bp_ids": duties},
                            {"employee_id": e.id, "date": other.isoformat(), "status": d.WEEKLY_OFF, "bp_ids": []},
                        ],
                    })
    return swaps[:5]


def _summary(ctx, bp_id, day, ranked) -> str:
    valid = [o for o in ranked if o["valid"]]
    label = ctx.bp_label(bp_id)
    if valid:
        top = valid[0]
        return f"{len(valid)} option(s) cover {label} on {fmt(day)} without breaking a rule. Best: {top['name']}."
    if ranked:
        return f"Nobody can cover {label} on {fmt(day)} without breaking a rule. Each option below shows what it would break."
    return f"Nobody is qualified to cover {label} on {fmt(day)}. Allocate a backup in setup, or record this as a known gap."


def employee_impact(inp: d.RosterInput, roster: d.Roster, trial: d.Roster) -> dict:
    """Before-and-after view of any change, including which brands it touches."""
    ctx = Context(inp)
    changes = compare(validate(inp, roster), validate(inp, trial))
    gaps = [i for i in changes["introduced"] if i.category == "coverage" and i.severity == d.BLOCKER]
    brands = sorted({ctx.brands[i.brand_id].name for i in gaps if i.brand_id in ctx.brands})
    return {
        "resolved": changes["resolved"],
        "introduced": changes["introduced"],
        "gap_count": len(gaps),
        "brands_affected": brands,
    }
