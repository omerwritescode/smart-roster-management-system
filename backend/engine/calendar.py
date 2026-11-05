"""Operating days, coverage requirements and rule definitions shared by the engine.

This module defines what the rules *are*. The solver turns them into constraints
and the validator checks them independently against the finished roster.
"""
from __future__ import annotations

import calendar as _stdlib_calendar
from dataclasses import dataclass
from datetime import date, timedelta

from . import domain as d


LEAVE_STATUS = {"planned": d.LEAVE, "sick": d.LEAVE, "comp_off": d.COMP_OFF, "unavailable": d.UNAVAILABLE}


def month_days(year: int, month: int) -> list[date]:
    last = _stdlib_calendar.monthrange(year, month)[1]
    return [date(year, month, i) for i in range(1, last + 1)]


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def shifts_overlap(a: d.Shift, b: d.Shift) -> bool:
    """Two different shifts clash when their hours overlap on the same day.

    Two allocations on the same shift do not clash in time; the workload limit
    decides whether one person can carry both.
    """
    if a.id == b.id:
        return False
    return a.start_min < b.end_min and b.start_min < a.end_min


def rest_minutes(first: d.Shift, next_day: d.Shift) -> int:
    return next_day.start_min + 1440 - first.end_min


@dataclass(frozen=True)
class WeekNeed:
    """Weekly offs one employee needs in one Monday-Sunday week."""
    monday: date
    days: tuple[date, ...]  # the days of this week inside the month
    need: int  # minimum weekly offs inside the month
    upper: int  # maximum weekly offs inside the month
    allowed: tuple[date, ...] | None  # set for fixed and rotating policies


class Context:
    """Indexes over a RosterInput, so rule lookups are simple and fast."""

    def __init__(self, inp: d.RosterInput):
        self.inp = inp
        self.days = month_days(inp.year, inp.month)
        self.first_day = self.days[0]
        self.last_day = self.days[-1]
        self.employees = {e.id: e for e in inp.employees}
        self.shifts = {s.id: s for s in inp.shifts}
        self.brands = {b.id: b for b in inp.brands}
        self.processes = {p.id: p for p in inp.processes}
        self.bps = {bp.id: bp for bp in inp.brand_processes}
        self.holidays = {h.date: h.name for h in inp.holidays}

        self._rules: dict[str, dict] = {}
        for r in inp.coverage_rules:
            bucket = self._rules.setdefault(
                r.brand_process_id, {"default": None, "weekday": {}, "date": {}}
            )
            if r.rule_type == "date":
                bucket["date"][r.date] = r.min_staff
            elif r.rule_type == "weekday":
                bucket["weekday"][r.weekday] = r.min_staff
            else:
                bucket["default"] = r.min_staff

        self.allocs_by_employee: dict[str, list[d.Allocation]] = {}
        self.allocs_by_process: dict[str, list[d.Allocation]] = {}
        for a in inp.allocations:
            if a.brand_process_id not in self.bps or a.employee_id not in self.employees:
                continue
            self.allocs_by_employee.setdefault(a.employee_id, []).append(a)
            self.allocs_by_process.setdefault(a.brand_process_id, []).append(a)

        self.blocked: dict[tuple[str, date], str] = {}
        self.pending: dict[tuple[str, date], str] = {}
        for lv in inp.leaves:
            if lv.status == "rejected":
                continue
            target = self.blocked if lv.status == "approved" else self.pending
            current = lv.start
            while current <= lv.end:
                target[(lv.employee_id, current)] = lv.leave_type
                current += timedelta(days=1)

        self.history: dict[tuple[str, date], d.HistoryDay] = {
            (h.employee_id, h.date): h for h in inp.history
        }

        self._weeks: list[tuple[date, list[date]]] = []
        for day in self.days:
            monday = monday_of(day)
            if not self._weeks or self._weeks[-1][0] != monday:
                self._weeks.append((monday, []))
            self._weeks[-1][1].append(day)

    # ------------------------------------------------------------ brand calendar
    def calendar_open(self, bp: d.BrandProcess, day: date) -> bool:
        is_holiday = day in self.holidays
        if bp.calendar_type == d.ALL_DAYS:
            return True
        if bp.calendar_type == d.DAILY_EXCEPT_HOLIDAYS:
            return not is_holiday
        if bp.calendar_type == d.SUNDAYS_HOLIDAYS_OFF:
            return not is_holiday and day.weekday() != d.SUNDAY
        if bp.calendar_type == d.CUSTOM:
            if is_holiday and bp.holidays_closed:
                return False
            return day.weekday() in bp.weekday_mask
        raise ValueError(f"Unknown calendar type: {bp.calendar_type}")

    def required(self, bp_id: str, day: date) -> int:
        """Minimum staff for a process on a day. The most specific rule wins.

        A date rule overrides the calendar, so a brand can open for a sale on a
        day it normally closes, or close on a day it normally opens (minimum 0).
        """
        bp = self.bps[bp_id]
        rules = self._rules.get(bp_id, {"default": None, "weekday": {}, "date": {}})
        if day in rules["date"]:
            return rules["date"][day]
        if not self.calendar_open(bp, day):
            return 0
        if day.weekday() in rules["weekday"]:
            return rules["weekday"][day.weekday()]
        return rules["default"] if rules["default"] is not None else 1

    # ------------------------------------------------------------ allocations
    @staticmethod
    def _alloc_active(a: d.Allocation, day: date) -> bool:
        if a.effective_from and day < a.effective_from:
            return False
        if a.effective_to and day > a.effective_to:
            return False
        return True

    def employee_allocations(self, employee_id: str, day: date) -> list[d.Allocation]:
        return [
            a for a in self.allocs_by_employee.get(employee_id, []) if self._alloc_active(a, day)
        ]

    def process_allocations(self, bp_id: str, day: date) -> list[d.Allocation]:
        return [a for a in self.allocs_by_process.get(bp_id, []) if self._alloc_active(a, day)]

    def allocation_for(self, employee_id: str, bp_id: str, day: date) -> d.Allocation | None:
        for a in self.employee_allocations(employee_id, day):
            if a.brand_process_id == bp_id:
                return a
        return None

    # ------------------------------------------------------------ names
    def bp_label(self, bp_id: str) -> str:
        bp = self.bps.get(bp_id)
        if bp is None:
            return bp_id
        brand = self.brands.get(bp.brand_id)
        process = self.processes.get(bp.process_id)
        return f"{brand.name if brand else bp.brand_id} {process.code if process else bp.process_id}"

    def employee_name(self, employee_id: str) -> str:
        e = self.employees.get(employee_id)
        return e.name if e else employee_id

    # ------------------------------------------------------------ weekly offs
    def rotation_weekday(self, employee: d.Employee, monday: date) -> int | None:
        if not employee.rotation_weekdays:
            return None
        index = monday.toordinal() // 7
        return employee.rotation_weekdays[index % len(employee.rotation_weekdays)]

    def weeks(self) -> list[tuple[date, list[date]]]:
        return self._weeks

    def week_need(self, employee: d.Employee, monday: date, days: list[date]) -> WeekNeed:
        """How many weekly offs this employee needs in this week of the month.

        - Fixed and rotating policies: the configured weekday, when it falls in the
          month and the person is not already on approved leave that day.
        - Solver-chosen: one per week by default. The part-week closing a month needs
          no off, because it can fall next month. The part-week opening a month counts
          when last month's roster is known (an off already taken is credited), or
          when it has four or more days.
        - A week with no available day needs no off.
        """
        available = [x for x in days if (employee.id, x) not in self.blocked]

        if employee.weekly_off_policy in ("fixed", "rotating"):
            if employee.weekly_off_policy == "fixed":
                targets = set(employee.fixed_off_weekdays)
            else:
                weekday = self.rotation_weekday(employee, monday)
                targets = {weekday} if weekday is not None else set()
            allowed = tuple(x for x in available if x.weekday() in targets)
            return WeekNeed(monday, tuple(days), len(allowed), len(allowed), allowed)

        before = [monday + timedelta(days=i) for i in range((days[0] - monday).days)]
        known = [self.history.get((employee.id, x)) for x in before]
        history_known = bool(before) and all(k is not None for k in known)
        taken = sum(1 for k in known if k is not None and k.status == d.WEEKLY_OFF)
        remaining = max(0, employee.offs_per_week - taken)

        full_week = len(days) == 7
        closing_part = not full_week and not before
        if full_week or history_known or (before and len(days) >= 4):
            need = min(remaining, len(available))
        else:
            need = 0
        if closing_part:
            need = 0  # this week's off can fall next month, which will see this month as history
        return WeekNeed(monday, tuple(days), need, remaining, None)


def eligible_for_weekend_work(ctx: Context, employee_id: str) -> bool:
    """Someone whose regular work runs on at least one Sunday or holiday this month."""
    for day in ctx.days:
        if day.weekday() != d.SUNDAY and day not in ctx.holidays:
            continue
        for a in ctx.employee_allocations(employee_id, day):
            if a.role != d.BACKUP and ctx.required(a.brand_process_id, day) > 0:
                return True
    return False
