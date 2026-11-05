"""Template explanations built only from validator facts. This is the fallback for AI text."""
from __future__ import annotations

from . import domain as d

WHY = {
    "NO_AVAILABLE_EMPLOYEE": "The client needs this process open that day, and everyone allocated to it is away.",
    "INSUFFICIENT_STAFFING": "Fewer people are working this process than the minimum set for that day.",
    "MULTI_BRAND_IMPACT": "One person holds work at several brands, so a single absence reaches more than one client.",
    "NO_BACKUP_CONFIGURED": "A person needs weekly offs, so a process with more required days than they can work needs a second person.",
    "WEEKLY_OFF_MISSING": "Weekly offs are a mandatory rule. The solver never removes them; only a person can, with a written reason.",
    "MAX_CONSECUTIVE_EXCEEDED": "This limit protects employees from long unbroken runs of work.",
    "LEAVE_NOT_HONOURED": "Approved leave is a commitment, so the roster cannot schedule over it.",
    "SHIFT_CLASH": "These shift hours overlap, so one person cannot work both.",
    "REST_TOO_SHORT": "A late finish followed by an early start leaves too little rest.",
    "WORKLOAD_EXCEEDED": "This day adds up to more work than one person's limit allows.",
    "NOT_ALLOCATED": "Only people allocated to a process are treated as able to do it.",
    "PREFERRED_OFF_MISSED": "Preferences give way to required client coverage, as the rules intend.",
    "AVOIDED_SHIFT_USED": "This is a preference, so the roster can still use the shift when it needs to.",
    "STRETCH_USED": "Cover work is pushing this person past a normal day, within their allowed limit.",
    "SUNDAY_HOLIDAY_IMBALANCE": "Some people carry more Sundays and holidays than others this month.",
    "PENDING_LEAVE_CLASH": "This request is not approved yet, so it has not changed the roster. Approving it would.",
}


def template_explanation(issue: d.Issue | dict) -> str:
    get = issue.get if isinstance(issue, dict) else lambda k, default=None: getattr(issue, k, default)
    code = get("code")
    parts = [get("message", "")]
    why = WHY.get(code)
    if why:
        parts.append(why)
    facts = get("facts", {}) or {}
    causes = facts.get("causes") or []
    if "weekly_off" in causes:
        parts.append("A weekly off is part of this gap. It stays in place, because coverage is solved with backups and never by removing someone's rest day.")
    if "leave" in causes:
        parts.append("Approved leave is part of this gap, so it needs someone else or a change to the leave.")
    if facts.get("holiday"):
        parts.append(f"This date is {facts['holiday']}, and anyone who covers it earns a comp-off.")
    suggestion = get("suggestion", "")
    if suggestion:
        parts.append(f"What to do: {suggestion}")
    return " ".join(p for p in parts if p)
