"""Build engine inputs straight from the seed data, with no database."""
from __future__ import annotations

from datetime import date, time

from backend.db import seed_data as s
from backend.engine import domain as d


def minutes(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def sample_input(year: int = 2026, month: int = 12) -> d.RosterInput:
    return d.RosterInput(
        year=year,
        month=month,
        employees=[
            d.Employee(id=e[0], name=e[1], pod_id=e[2], title=e[3], weekly_off_policy=e[4],
                       fixed_off_weekdays=tuple(e[5]), rotation_weekdays=tuple(e[6]))
            for e in s.EMPLOYEES
        ],
        shifts=[d.Shift(x[0], x[1], minutes(x[2]), minutes(x[3])) for x in s.SHIFTS],
        brands=[d.Brand(b[0], b[1], b[2]) for b in s.BRANDS],
        processes=[d.Process(*p) for p in s.PROCESSES],
        brand_processes=[
            d.BrandProcess(id=r[0], brand_id=r[1], process_id=r[2], calendar_type=r[3], weekday_mask=tuple(r[4]), shift_id=r[5])
            for r in s.brand_processes()
        ],
        coverage_rules=[d.CoverageRule(r[0], r[1], r[4], r[2], r[3], r[5]) for r in s.COVERAGE_RULES],
        allocations=[d.Allocation(r[0], r[1], r[2], r[3], r[4]) for r in s.allocations()],
        leaves=[d.Leave(x[0], x[1], x[2], x[3], x[4], x[5]) for x in s.LEAVES],
        preferences=[d.Preference(p[0], p[1], p[2], p[3], p[4], p[5]) for p in s.PREFERENCES],
        holidays=[d.Holiday(h[0], h[1]) for h in s.HOLIDAYS],
        comp_off_balances={k: v for k, v in s.COMP_OFF_OPENING},
    )


__all__ = ["sample_input", "date", "time"]
