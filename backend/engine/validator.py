"""The single source of truth for whether a roster is valid.

Solver output and manual edits go through these same checks, so the solver never
marks its own work. The module is pure: it takes data in and returns a list of
issues. It imports nothing from the solver.

Severity:
- blocker: a mandatory rule is broken; stops publishing unless overridden with a reason
- warning: a preference or fairness aim was missed, or something needs a look
- info: useful context that needs no action
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from . import domain as d
from .calendar import Context, eligible_for_weekend_work, rest_minutes, shifts_overlap

STATUS_WORDS = {
    d.WEEKLY_OFF: "on weekly off",
    d.LEAVE: "on leave",
    d.COMP_OFF: "on comp-off",
    d.UNAVAILABLE: "unavailable",
    d.HOLIDAY: "off for the holiday",
    d.IDLE: "on duty but not assigned",
    d.WORK: "working elsewhere",
}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def fmt(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()][:3]} {day.day} {day.strftime('%b')}"


def validate(inp: d.RosterInput, roster: d.Roster) -> list[d.Issue]:
    ctx = Context(inp)
    by_emp_day = roster.by_employee_day()
    by_bp_day = roster.by_process_day()
    issues: list[d.Issue] = []
    issues += _check_days_present(ctx, roster)
    issues += _check_assignments(ctx, roster, by_emp_day)
    issues += _check_day_limits(ctx, roster, by_emp_day)
    issues += _check_rest(ctx, by_emp_day)
    issues += _check_weekly_offs(ctx, roster, by_emp_day)
    issues += _check_consecutive(ctx, roster)
    coverage = _check_coverage(ctx, roster, by_bp_day, by_emp_day)
    issues += coverage
    issues += _check_cross_brand_impact(ctx, roster, coverage)
    issues += _check_structure(ctx, coverage)
    issues += _check_preferences(ctx, roster, by_emp_day)
    issues += _check_fairness(ctx, roster)
    issues += _check_availability_notes(ctx, roster, by_emp_day)
    order = {d.BLOCKER: 0, d.WARNING: 1, d.INFO: 2}
    issues.sort(key=lambda i: (order[i.severity], i.date or date.max, i.code, i.key))
    return issues


# ---------------------------------------------------------------- never broken
def _check_days_present(ctx: Context, roster: d.Roster) -> list[d.Issue]:
    out = []
    for e in ctx.employees.values():
        missing = [x for x in ctx.days if (e.id, x) not in roster.days]
        if missing:
            out.append(d.Issue(
                code="DAYS_MISSING", severity=d.BLOCKER, category="rule", employee_id=e.id,
                message=f"{e.name} has no roster entry on {len(missing)} day(s), starting {fmt(missing[0])}.",
                suggestion="Regenerate the roster so this employee is included.",
                facts={"employee": e.name, "days": [x.isoformat() for x in missing]},
            ))
    return out


def _check_assignments(ctx, roster, by_emp_day) -> list[d.Issue]:
    out = []
    for e in ctx.employees.values():
        for day in ctx.days:
            rec = roster.days.get((e.id, day))
            todays = by_emp_day.get((e.id, day), [])
            blocked = ctx.blocked.get((e.id, day))
            if blocked and rec and rec.status not in d.ABSENT_STATUSES:
                out.append(d.Issue(
                    code="LEAVE_NOT_HONOURED", severity=d.BLOCKER, category="rule", date=day, employee_id=e.id,
                    message=f"{e.name} has approved {blocked.replace('_', '-')} leave on {fmt(day)} but is rostered as {rec.status.replace('_', ' ')}.",
                    suggestion="Move this duty to someone else, or change the leave first.",
                    facts={"employee": e.name, "date": day.isoformat(), "leave_type": blocked, "status": rec.status},
                ))
            if rec and rec.status != d.WORK and todays:
                out.append(d.Issue(
                    code="ASSIGNED_WHEN_OFF", severity=d.BLOCKER, category="rule", date=day, employee_id=e.id,
                    message=f"{e.name} is marked {rec.status.replace('_', ' ')} on {fmt(day)} but has {len(todays)} assignment(s).",
                    suggestion="Set the day to working or remove the assignments.",
                    facts={"employee": e.name, "date": day.isoformat(), "status": rec.status},
                ))
            for a in todays:
                if a.brand_process_id not in ctx.bps:
                    continue
                label = ctx.bp_label(a.brand_process_id)
                if ctx.allocation_for(e.id, a.brand_process_id, day) is None:
                    out.append(d.Issue(
                        code="NOT_ALLOCATED", severity=d.BLOCKER, category="rule", date=day, employee_id=e.id,
                        brand_process_id=a.brand_process_id,
                        message=f"{e.name} is assigned to {label} on {fmt(day)} without an allocation to that process.",
                        suggestion=f"Add {e.name} as a backup on {label}, or assign someone already allocated.",
                        facts={"employee": e.name, "process": label, "date": day.isoformat()},
                    ))
                if ctx.required(a.brand_process_id, day) == 0:
                    out.append(d.Issue(
                        code="ASSIGNED_ON_CLOSED_DAY", severity=d.WARNING, category="rule", date=day, employee_id=e.id,
                        brand_process_id=a.brand_process_id,
                        message=f"{e.name} is assigned to {label} on {fmt(day)}, when that process is closed.",
                        suggestion="Remove the assignment, or add a date rule if the process should open that day.",
                        facts={"employee": e.name, "process": label, "date": day.isoformat()},
                    ))
    return out


def _check_day_limits(ctx, roster, by_emp_day) -> list[d.Issue]:
    out = []
    for (emp_id, day), todays in by_emp_day.items():
        e = ctx.employees.get(emp_id)
        if e is None or not (ctx.first_day <= day <= ctx.last_day):
            continue
        load = sum(a.share for a in todays)
        has_cover = any(a.is_cover for a in todays)
        labels = [ctx.bp_label(a.brand_process_id) for a in todays]
        if load > e.stretch_limit or (load > d.FULL_DAY and not has_cover):
            limit = e.stretch_limit if has_cover else d.FULL_DAY
            out.append(d.Issue(
                code="WORKLOAD_EXCEEDED", severity=d.BLOCKER, category="rule", date=day, employee_id=emp_id,
                message=f"{e.name} has {load}% of a day on {fmt(day)} ({', '.join(labels)}). The limit is {limit}%.",
                suggestion="Move one of these processes to someone with spare capacity.",
                facts={"employee": e.name, "load": load, "limit": limit, "processes": labels, "date": day.isoformat()},
            ))
        elif load > d.FULL_DAY:
            out.append(d.Issue(
                code="STRETCH_USED", severity=d.WARNING, category="preference", date=day, employee_id=emp_id,
                message=f"{e.name} is stretched to {load}% on {fmt(day)} to cover ({', '.join(labels)}).",
                suggestion="Acceptable occasionally. Assign someone with more spare capacity if it recurs.",
                facts={"employee": e.name, "load": load, "processes": labels, "date": day.isoformat()},
            ))
        for i in range(len(todays)):
            for j in range(i + 1, len(todays)):
                s1 = ctx.shifts.get(todays[i].shift_id)
                s2 = ctx.shifts.get(todays[j].shift_id)
                if s1 and s2 and shifts_overlap(s1, s2):
                    out.append(d.Issue(
                        code="SHIFT_CLASH", severity=d.BLOCKER, category="shift", date=day, employee_id=emp_id,
                        brand_process_id=todays[i].brand_process_id,
                        extra_key=todays[j].brand_process_id,
                        message=f"{e.name} has overlapping shifts on {fmt(day)}: {labels[i]} ({s1.name}) and {labels[j]} ({s2.name}).",
                        suggestion="One person cannot work overlapping shifts. Move one process to someone else.",
                        facts={"employee": e.name, "date": day.isoformat(), "first": labels[i], "second": labels[j],
                               "first_shift": s1.name, "second_shift": s2.name},
                    ))
    return out


def _check_rest(ctx, by_emp_day) -> list[d.Issue]:
    out = []
    minimum = ctx.inp.settings.min_rest_minutes
    for e in ctx.employees.values():
        previous_day = ctx.first_day - timedelta(days=1)
        hist = ctx.history.get((e.id, previous_day))
        prev_shifts = [ctx.shifts[s] for s in (hist.shift_ids if hist else ()) if s in ctx.shifts]
        for day in ctx.days:
            today = [ctx.shifts[a.shift_id] for a in by_emp_day.get((e.id, day), []) if a.shift_id in ctx.shifts]
            found = False
            for p in prev_shifts:
                for t in today:
                    rest = rest_minutes(p, t)
                    if rest < minimum and not found:
                        found = True
                        out.append(d.Issue(
                            code="REST_TOO_SHORT", severity=d.BLOCKER, category="shift", date=day, employee_id=e.id,
                            message=f"{e.name} gets {rest // 60}h {rest % 60}m of rest before {fmt(day)} ({p.name} then {t.name}). The minimum is {minimum // 60}h.",
                            suggestion="Change one of the two shifts or give the person a different day.",
                            facts={"employee": e.name, "date": day.isoformat(), "rest_minutes": rest, "minimum": minimum,
                                   "previous_shift": p.name, "shift": t.name},
                        ))
            prev_shifts = today
    return out


def _check_weekly_offs(ctx, roster, by_emp_day) -> list[d.Issue]:
    out = []
    for e in ctx.employees.values():
        for monday, days in ctx.weeks():
            need = ctx.week_need(e, monday, days)
            offs = [x for x in days if (r := roster.days.get((e.id, x))) and r.status == d.WEEKLY_OFF]
            if len(offs) < need.need:
                out.append(d.Issue(
                    code="WEEKLY_OFF_MISSING", severity=d.BLOCKER, category="rule", date=days[0], employee_id=e.id,
                    message=f"{e.name} has {len(offs)} weekly off(s) in the week of {fmt(monday)}. {need.need} required.",
                    suggestion="Give this person a day off in that week. Working through it needs a written override and earns a comp-off.",
                    facts={"employee": e.name, "week_of": monday.isoformat(), "offs": len(offs), "required": need.need},
                ))
            elif len(offs) > need.upper:
                out.append(d.Issue(
                    code="WEEKLY_OFF_EXCESS", severity=d.WARNING, category="rule", date=days[0], employee_id=e.id,
                    message=f"{e.name} has {len(offs)} weekly offs in the week of {fmt(monday)}. {need.upper} expected.",
                    suggestion="Check whether the extra day off was intended.",
                    facts={"employee": e.name, "week_of": monday.isoformat(), "offs": len(offs), "expected": need.upper},
                ))
            if need.allowed is not None:
                for x in offs:
                    if x not in need.allowed:
                        out.append(d.Issue(
                            code="WEEKLY_OFF_PATTERN", severity=d.WARNING, category="rule", date=x, employee_id=e.id,
                            message=f"{e.name} has a weekly off on {fmt(x)}, outside their {e.weekly_off_policy} pattern.",
                            suggestion="Confirm the change with the employee, or restore the pattern.",
                            facts={"employee": e.name, "date": x.isoformat(), "policy": e.weekly_off_policy},
                        ))
    return out


def _check_consecutive(ctx, roster) -> list[d.Issue]:
    out = []
    for e in ctx.employees.values():
        run = 0
        cursor = ctx.first_day - timedelta(days=1)
        while (h := ctx.history.get((e.id, cursor))) and h.status == d.WORK:
            run += 1
            cursor -= timedelta(days=1)
        reported = False
        for day in ctx.days:
            r = roster.days.get((e.id, day))
            if r and r.status == d.WORK:
                run += 1
                if run > e.max_consecutive_days and not reported:
                    reported = True
                    out.append(d.Issue(
                        code="MAX_CONSECUTIVE_EXCEEDED", severity=d.BLOCKER, category="rule", date=day, employee_id=e.id,
                        message=f"{e.name} reaches {run} consecutive working days on {fmt(day)}. The limit is {e.max_consecutive_days}.",
                        suggestion="Give this person a day off inside this run.",
                        facts={"employee": e.name, "date": day.isoformat(), "run": run, "limit": e.max_consecutive_days},
                    ))
            else:
                run = 0
                reported = False
    return out


# ---------------------------------------------------------------- coverage
def _check_coverage(ctx, roster, by_bp_day, by_emp_day) -> list[d.Issue]:
    out = []
    for bp in ctx.bps.values():
        for day in ctx.days:
            required = ctx.required(bp.id, day)
            if required <= 0:
                continue
            staffed = {a.employee_id for a in by_bp_day.get((bp.id, day), [])}
            if len(staffed) >= required:
                continue
            people, causes, free = [], set(), 0
            for a in ctx.process_allocations(bp.id, day):
                if a.employee_id in staffed:
                    continue
                rec = roster.days.get((a.employee_id, day))
                status = rec.status if rec else d.IDLE
                reason = STATUS_WORDS.get(status, status)
                clashing = [
                    x for x in by_emp_day.get((a.employee_id, day), [])
                    if x.shift_id in ctx.shifts and shifts_overlap(ctx.shifts[x.shift_id], ctx.shifts[bp.shift_id])
                ]
                if clashing:
                    names = ", ".join(ctx.bp_label(x.brand_process_id) for x in clashing)
                    reason = f"working {names}, whose shift overlaps this one"
                people.append({
                    "name": ctx.employee_name(a.employee_id), "employee_id": a.employee_id,
                    "role": a.role, "status": status, "reason": reason,
                })
                if a.role != d.BACKUP and status == d.WEEKLY_OFF:
                    causes.add("weekly_off")
                if a.role != d.BACKUP and status in d.ABSENT_STATUSES:
                    causes.add("leave")
                if a.role != d.BACKUP and clashing:
                    causes.add("shift_clash")
                elif a.role != d.BACKUP and status in (d.WORK, d.IDLE):
                    causes.add("capacity")
                if status not in d.ABSENT_STATUSES and status != d.WEEKLY_OFF:
                    free += 1
            label = ctx.bp_label(bp.id)
            who = "; ".join(f"{p['name']} ({p['role']}) is {p['reason']}" for p in people) or "nobody is allocated to this process"
            none_left = not staffed and free == 0
            code = "NO_AVAILABLE_EMPLOYEE" if none_left else "INSUFFICIENT_STAFFING"
            head = (
                f"{label} needs {required} on {fmt(day)} and no allocated employee is available."
                if none_left
                else f"{label} needs {required} on {fmt(day)} and has {len(staffed)}."
            )
            has_backup = any(a.role == d.BACKUP for a in ctx.process_allocations(bp.id, day))
            suggestion = (
                "Open the backup options for this gap to compare who can cover it."
                if has_backup or people
                else f"Allocate someone to {label}, then regenerate."
            )
            out.append(d.Issue(
                code=code, severity=d.BLOCKER, category="coverage", date=day, brand_process_id=bp.id,
                brand_id=bp.brand_id, message=f"{head} {who[0].upper() + who[1:]}.", suggestion=suggestion,
                facts={"process": label, "date": day.isoformat(), "required": required, "staffed": len(staffed),
                       "short_by": required - len(staffed), "allocated_people": people, "causes": sorted(causes),
                       "has_backup": has_backup, "holiday": ctx.holidays.get(day)},
            ))
    return out


def _check_cross_brand_impact(ctx, roster, coverage: list[d.Issue]) -> list[d.Issue]:
    """One person's absence causing gaps at more than one brand on one day."""
    out = []
    by_person_day: dict[tuple[str, date], list[d.Issue]] = defaultdict(list)
    for gap in coverage:
        for p in gap.facts["allocated_people"]:
            if p["role"] != d.BACKUP and p["status"] in (d.ABSENT_STATUSES | {d.WEEKLY_OFF}):
                by_person_day[(p["employee_id"], gap.date)].append(gap)
    for (emp_id, day), gaps in by_person_day.items():
        brands = {g.brand_id for g in gaps}
        if len(brands) < 2:
            continue
        names = sorted({ctx.brands[b].name for b in brands if b in ctx.brands})
        status = roster.days[(emp_id, day)].status
        out.append(d.Issue(
            code="MULTI_BRAND_IMPACT", severity=d.WARNING, category="coverage", date=day, employee_id=emp_id,
            message=f"{ctx.employee_name(emp_id)} being {STATUS_WORDS.get(status, status)} on {fmt(day)} leaves gaps at {len(brands)} brands: {', '.join(names)}.",
            suggestion="Solve this person's absence first, since one change fixes several brands.",
            facts={"employee": ctx.employee_name(emp_id), "date": day.isoformat(), "status": status,
                   "brands": names, "processes": [g.facts["process"] for g in gaps]},
        ))
    return out


def _check_structure(ctx, coverage: list[d.Issue]) -> list[d.Issue]:
    """Monthly problems that no daily schedule can fix."""
    out = []
    gap_days: dict[str, list[date]] = defaultdict(list)
    for gap in coverage:
        gap_days[gap.brand_process_id].append(gap.date)
    for bp_id, days in gap_days.items():
        allocs = ctx.allocs_by_process.get(bp_id, [])
        if any(a.role == d.BACKUP for a in allocs):
            continue
        label = ctx.bp_label(bp_id)
        regular = len({a.employee_id for a in allocs})
        out.append(d.Issue(
            code="NO_BACKUP_CONFIGURED", severity=d.WARNING, category="data", brand_process_id=bp_id,
            brand_id=ctx.bps[bp_id].brand_id,
            message=f"{label} has {regular} allocated employee(s), no backup, and {len(days)} uncovered day(s) this month.",
            suggestion=f"Allocate a backup to {label}. It cannot be covered every required day otherwise, because weekly offs are never removed.",
            facts={"process": label, "uncovered_days": [x.isoformat() for x in days], "allocated": regular},
        ))
    for e in ctx.employees.values():
        regular = [a for a in ctx.employee_allocations(e.id, ctx.first_day) if a.role != d.BACKUP]
        total = sum(a.share for a in regular)
        if total > d.FULL_DAY:
            out.append(d.Issue(
                code="OVERALLOCATED", severity=d.WARNING, category="data", employee_id=e.id,
                message=f"{e.name}'s regular allocations add up to {total}% of a day. Some will go uncovered on days they all operate.",
                suggestion="Reduce the workload shares or move a process to someone else.",
                facts={"employee": e.name, "total_share": total},
            ))
    return out


# ---------------------------------------------------------------- preferences
def _check_preferences(ctx, roster, by_emp_day) -> list[d.Issue]:
    out = []
    for p in ctx.inp.preferences:
        e = ctx.employees.get(p.employee_id)
        if e is None:
            continue
        if p.pref_type == "off_date" and p.date and ctx.first_day <= p.date <= ctx.last_day:
            r = roster.days.get((e.id, p.date))
            if r and r.status == d.WORK:
                out.append(d.Issue(
                    code="PREFERRED_OFF_MISSED", severity=d.WARNING, category="preference", date=p.date, employee_id=e.id,
                    message=f"{e.name} asked for {fmt(p.date)} off and is working.",
                    suggestion="Required coverage takes priority over a preferred day off. Swap with a backup if you can.",
                    facts={"employee": e.name, "date": p.date.isoformat(), "weight": p.weight},
                ))
        elif p.pref_type == "off_weekday" and p.weekday is not None:
            for monday, days in ctx.weeks():
                target = [x for x in days if x.weekday() == p.weekday]
                if not target or len(days) < 4:
                    continue
                x = target[0]
                r = roster.days.get((e.id, x))
                if r and r.status == d.WORK:
                    out.append(d.Issue(
                        code="PREFERRED_OFF_MISSED", severity=d.WARNING, category="preference", date=x, employee_id=e.id,
                        message=f"{e.name} prefers {WEEKDAYS[p.weekday]}s off and is working {fmt(x)}.",
                        suggestion="Required coverage takes priority over a preferred day off.",
                        facts={"employee": e.name, "date": x.isoformat(), "weekday": WEEKDAYS[p.weekday], "weight": p.weight},
                    ))
        elif p.pref_type == "avoid_shift" and p.shift_id:
            days_hit = sorted({a.date for (emp, _), items in by_emp_day.items() if emp == e.id
                               for a in items if a.shift_id == p.shift_id})
            if days_hit:
                name = ctx.shifts[p.shift_id].name if p.shift_id in ctx.shifts else p.shift_id
                out.append(d.Issue(
                    code="AVOIDED_SHIFT_USED", severity=d.WARNING, category="preference", employee_id=e.id, extra_key=p.shift_id,
                    message=f"{e.name} prefers to avoid the {name} shift and has it on {len(days_hit)} day(s).",
                    suggestion="Allowed, because this is a preference and not a rule.",
                    facts={"employee": e.name, "shift": name, "days": [x.isoformat() for x in days_hit], "weight": p.weight},
                ))
    return out


def sunday_holiday_counts(ctx: Context, roster: d.Roster) -> dict[str, int]:
    counts = {}
    for e in ctx.employees.values():
        if not eligible_for_weekend_work(ctx, e.id):
            continue
        counts[e.id] = sum(
            1 for day in ctx.days
            if (day.weekday() == d.SUNDAY or day in ctx.holidays)
            and (r := roster.days.get((e.id, day))) and r.status == d.WORK
        )
    return counts


def _check_fairness(ctx, roster) -> list[d.Issue]:
    counts = sunday_holiday_counts(ctx, roster)
    if len(counts) < 2:
        return []
    high, low = max(counts.values()), min(counts.values())
    if high - low < ctx.inp.settings.fairness_spread_warning:
        return []
    most = sorted(ctx.employee_name(k) for k, v in counts.items() if v == high)
    least = sorted(ctx.employee_name(k) for k, v in counts.items() if v == low)
    return [d.Issue(
        code="SUNDAY_HOLIDAY_IMBALANCE", severity=d.WARNING, category="fairness",
        message=f"Sunday and holiday work is uneven: from {low} to {high} days. Most: {', '.join(most[:4])}.",
        suggestion="Compare the fairness-first plan, or add backups for the most loaded people.",
        facts={"high": high, "low": low, "most": most, "least": least},
    )]


# ---------------------------------------------------------------- notes
def _check_availability_notes(ctx, roster, by_emp_day) -> list[d.Issue]:
    out = []
    for (emp_id, day), kind in ctx.pending.items():
        if not (ctx.first_day <= day <= ctx.last_day) or emp_id not in ctx.employees:
            continue
        r = roster.days.get((emp_id, day))
        if r and r.status == d.WORK:
            out.append(d.Issue(
                code="PENDING_LEAVE_CLASH", severity=d.WARNING, category="rule", date=day, employee_id=emp_id,
                message=f"{ctx.employee_name(emp_id)} has a pending {kind.replace('_', '-')} request on {fmt(day)} and is rostered to work.",
                suggestion="Check the impact of this request before approving it.",
                facts={"employee": ctx.employee_name(emp_id), "date": day.isoformat(), "leave_type": kind},
            ))
    for (emp_id, day), r in roster.days.items():
        if emp_id not in ctx.employees or not (ctx.first_day <= day <= ctx.last_day):
            continue
        holiday = ctx.holidays.get(day)
        if holiday and r.status == d.WORK:
            out.append(d.Issue(
                code="HOLIDAY_WORKED", severity=d.INFO, category="info", date=day, employee_id=emp_id,
                message=f"{ctx.employee_name(emp_id)} works {holiday} ({fmt(day)}) and earns a comp-off when this roster is published.",
                facts={"employee": ctx.employee_name(emp_id), "date": day.isoformat(), "holiday": holiday},
            ))
        elif holiday and r.status == d.WEEKLY_OFF:
            out.append(d.Issue(
                code="WEEKLY_OFF_ON_HOLIDAY", severity=d.INFO, category="info", date=day, employee_id=emp_id,
                message=f"{ctx.employee_name(emp_id)}'s weekly off falls on {holiday} ({fmt(day)}).",
                suggestion="Worth a look: the employee loses a separate rest day that week.",
                facts={"employee": ctx.employee_name(emp_id), "date": day.isoformat(), "holiday": holiday},
            ))
    used: dict[str, int] = defaultdict(int)
    for (emp_id, day), kind in ctx.blocked.items():
        if kind == "comp_off" and ctx.first_day <= day <= ctx.last_day:
            used[emp_id] += 1
    for emp_id, count in used.items():
        balance = ctx.inp.comp_off_balances.get(emp_id)
        if balance is not None and balance < 0 and emp_id in ctx.employees:
            out.append(d.Issue(
                code="COMP_OFF_OVERDRAWN", severity=d.WARNING, category="rule", employee_id=emp_id,
                message=f"{ctx.employee_name(emp_id)} has taken {count} comp-off day(s) this month and their balance is {balance}.",
                suggestion="Check the comp-off ledger or change the leave type.",
                facts={"employee": ctx.employee_name(emp_id), "balance": balance, "used_this_month": count},
            ))
    return out


# ---------------------------------------------------------------- helpers for callers
def blockers(issues: list[d.Issue]) -> list[d.Issue]:
    return [i for i in issues if i.severity == d.BLOCKER]


def compare(before: list[d.Issue], after: list[d.Issue]) -> dict[str, list[d.Issue]]:
    """What a change resolved and what it introduced."""
    old = {i.key: i for i in before}
    new = {i.key: i for i in after}
    return {
        "resolved": [old[k] for k in old if k not in new],
        "introduced": [new[k] for k in new if k not in old],
    }


def comp_off_entitlements(inp: d.RosterInput, roster: d.Roster) -> list[tuple[str, date, str]]:
    """Comp-offs earned by this roster: holidays worked, and weekly offs worked through."""
    ctx = Context(inp)
    earned: list[tuple[str, date, str]] = []
    for (emp_id, day), r in sorted(roster.days.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if emp_id not in ctx.employees or r.status != d.WORK:
            continue
        if day in ctx.holidays:
            earned.append((emp_id, day, f"Worked {ctx.holidays[day]}"))
        elif r.note == d.NOTE_WORKED_WEEKLY_OFF:
            earned.append((emp_id, day, "Worked a weekly off"))
    return earned
