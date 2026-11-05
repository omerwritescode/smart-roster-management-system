"""Alternative plans and the metrics used to compare any roster.

Every plan keeps the same mandatory rules. Coverage always outweighs preferences;
the plans differ only in how they spend the remaining freedom.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace

from . import domain as d
from .calendar import Context
from .solver import DEFAULT_WEIGHTS, SolveOptions, SolveResult, solve
from .validator import sunday_holiday_counts

PLANS = {
    "coverage_first": {
        "label": "Coverage first",
        "description": "Fills every required day using backups and stretch freely. Preferences come last.",
        "weights": replace(DEFAULT_WEIGHTS, backup_use=20, cross_pod_backup=10, stretch=30, max_cover_days=5,
                           preference=8, sunday_spread=10),
    },
    "fairness_first": {
        "label": "Fairness first",
        "description": "Spreads Sundays, holidays and backup duty as evenly as coverage allows.",
        "weights": replace(DEFAULT_WEIGHTS, sunday_spread=400, max_cover_days=150, preference=10),
    },
    "preference_first": {
        "label": "Preference first",
        "description": "Honours preferred days off and shifts wherever required coverage still holds.",
        "weights": replace(DEFAULT_WEIGHTS, preference=120, sunday_spread=10, max_cover_days=10),
    },
}


def options_for(plan: str, **overrides) -> SolveOptions:
    if plan not in PLANS:
        raise ValueError(f"Unknown plan: {plan}")
    return SolveOptions(weights=PLANS[plan]["weights"], **overrides)


def generate(inp: d.RosterInput, plan: str = "coverage_first", **overrides) -> SolveResult:
    return solve(inp, options_for(plan, **overrides))


def metrics(inp: d.RosterInput, roster: d.Roster, issues: list[d.Issue]) -> dict:
    ctx = Context(inp)
    by_bp_day = roster.by_process_day()
    required_slots = covered_slots = 0
    for bp in ctx.bps.values():
        for day in ctx.days:
            need = ctx.required(bp.id, day)
            if need <= 0:
                continue
            required_slots += need
            covered_slots += min(need, len({a.employee_id for a in by_bp_day.get((bp.id, day), [])}))

    severity = Counter(i.severity for i in issues)
    codes = Counter(i.code for i in issues)

    cover_people = {(a.employee_id, a.date) for a in roster.assignments if a.is_cover}
    cover_by_person = Counter(a.employee_id for a in {(x.employee_id, x.date): x for x in roster.assignments if x.is_cover}.values())
    weekend = sunday_holiday_counts(ctx, roster)
    statuses = Counter(r.status for r in roster.days.values())

    pref_total = pref_missed = 0
    for p in inp.preferences:
        if p.employee_id not in ctx.employees:
            continue
        if p.pref_type == "off_date" and p.date and ctx.first_day <= p.date <= ctx.last_day:
            pref_total += 1
        elif p.pref_type == "off_weekday":
            pref_total += sum(
                1 for _, days in ctx.weeks() if len(days) >= 4 and any(x.weekday() == p.weekday for x in days)
            )
    pref_missed = codes.get("PREFERRED_OFF_MISSED", 0)
    honoured = 100.0 if pref_total == 0 else round(100 * (pref_total - pref_missed) / pref_total, 1)

    coverage = 100.0 if required_slots == 0 else round(100 * covered_slots / required_slots, 2)
    spread = max(weekend.values()) - min(weekend.values()) if weekend else 0
    peak_cover = max(cover_by_person.values()) if cover_by_person else 0
    score = round(
        coverage * 0.7
        + honoured * 0.1
        + max(0, 100 - spread * 15) * 0.1
        + max(0, 100 - codes.get("STRETCH_USED", 0)) * 0.1,
        1,
    )
    return {
        "coverage_pct": coverage,
        "required_slots": required_slots,
        "covered_slots": covered_slots,
        "gap_slots": required_slots - covered_slots,
        "blockers": severity.get(d.BLOCKER, 0),
        "warnings": severity.get(d.WARNING, 0),
        "backup_days": len(cover_people),
        "peak_backup_days": peak_cover,
        "stretch_days": codes.get("STRETCH_USED", 0),
        "preferences_honoured_pct": honoured,
        "sunday_holiday_spread": spread,
        "sunday_holiday_low": min(weekend.values()) if weekend else 0,
        "sunday_holiday_high": max(weekend.values()) if weekend else 0,
        "working_days": statuses.get(d.WORK, 0),
        "weekly_offs": statuses.get(d.WEEKLY_OFF, 0),
        "score": score,
    }
