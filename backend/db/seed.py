"""Load the sample data. Also used by the app's "Reset demo data" button."""
from __future__ import annotations

import json
from datetime import date

from . import seed_data as s
from .database import insert_many

TABLES = (
    "audit_log, notifications, comp_off_ledger, approvals, ai_explanations, issue_overrides, issues, "
    "roster_assignments, roster_days, rosters, preferences, leaves, allocations, coverage_rules, "
    "brand_processes, app_settings, public_holidays, shifts, processes, brands, employees, pods"
)


def _rule_id(row) -> str:
    return f"rule-{row[0]}-{row[1]}-{row[2] if row[2] is not None else ''}{row[3] or ''}"


def reset(conn) -> dict:
    conn.execute(f"truncate {TABLES} restart identity cascade")
    insert_many(conn, "pods", ["id", "name"], [(p[0], p[1]) for p in s.PODS])
    insert_many(
        conn, "employees", ["id", "name", "pod_id", "title", "weekly_off_policy", "fixed_off_weekdays", "rotation_weekdays"],
        [(e[0], e[1], e[2], e[3], e[4], list(e[5]), list(e[6])) for e in s.EMPLOYEES],
    )
    for pod in s.PODS:
        conn.execute("update pods set lead_employee_id = %s where id = %s", (pod[2], pod[0]))
    insert_many(conn, "shifts", ["id", "name", "start_time", "end_time"], s.SHIFTS)
    insert_many(conn, "processes", ["id", "code", "name"], s.PROCESSES)
    insert_many(conn, "brands", ["id", "name", "pod_id"], [b[:3] for b in s.BRANDS])
    insert_many(conn, "public_holidays", ["date", "name", "kind"], s.HOLIDAYS)
    insert_many(
        conn, "brand_processes", ["id", "brand_id", "process_id", "calendar_type", "weekday_mask", "shift_id"],
        [(r[0], r[1], r[2], r[3], list(r[4]), r[5]) for r in s.brand_processes()],
    )
    insert_many(
        conn, "coverage_rules", ["id", "brand_process_id", "rule_type", "weekday", "date", "min_staff", "note"],
        [(_rule_id(r), *r) for r in s.COVERAGE_RULES],
    )
    insert_many(conn, "allocations", ["id", "employee_id", "brand_process_id", "role", "workload_share"], s.allocations())
    insert_many(conn, "leaves", ["id", "employee_id", "leave_type", "status", "start_date", "end_date", "reason"], s.LEAVES)
    insert_many(
        conn, "comp_off_ledger", ["employee_id", "delta", "entry_date", "reason"],
        [(emp, delta, date(2026, 11, 30), "Opening balance") for emp, delta in s.COMP_OFF_OPENING],
    )
    insert_many(
        conn, "comp_off_ledger", ["employee_id", "delta", "entry_date", "reason", "leave_id"],
        [(x[1], -((x[5] - x[4]).days + 1), x[4], "Comp-off taken", x[0]) for x in s.LEAVES if x[2] == "comp_off" and x[3] == "approved"],
    )
    insert_many(conn, "preferences", ["employee_id", "pref_type", "weekday", "date", "shift_id", "weight"], s.PREFERENCES)
    insert_many(conn, "app_settings", ["key", "value"], [(k, json.dumps(v)) for k, v in s.SETTINGS.items()])
    return {"employees": len(s.EMPLOYEES), "brands": len(s.BRANDS), "pods": len(s.PODS)}
