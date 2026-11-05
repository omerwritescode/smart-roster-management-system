"""Plain data types for the scheduling engine. No web or database code here."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

# Employee day statuses
WORK = "work"
WEEKLY_OFF = "weekly_off"
HOLIDAY = "holiday"
LEAVE = "leave"
COMP_OFF = "comp_off"
UNAVAILABLE = "unavailable"
IDLE = "idle"  # on duty, nothing to cover: available as spare capacity
ABSENT_STATUSES = {LEAVE, COMP_OFF, UNAVAILABLE}
ALL_STATUSES = {WORK, WEEKLY_OFF, HOLIDAY, LEAVE, COMP_OFF, UNAVAILABLE, IDLE}

# Calendar types
ALL_DAYS = "all_days"
DAILY_EXCEPT_HOLIDAYS = "daily_except_holidays"
SUNDAYS_HOLIDAYS_OFF = "sundays_holidays_off"
CUSTOM = "custom"

# Allocation roles
PRIMARY = "primary"
SECONDARY = "secondary"
BACKUP = "backup"

# Issue severities
BLOCKER = "blocker"
WARNING = "warning"
INFO = "info"

NOTE_WORKED_WEEKLY_OFF = "worked_weekly_off"
SUNDAY = 6
FULL_DAY = 100


@dataclass(frozen=True)
class Employee:
    id: str
    name: str
    pod_id: str | None = None
    title: str = "Associate"
    weekly_off_policy: str = "solver"  # solver | fixed | rotating
    fixed_off_weekdays: tuple[int, ...] = ()
    rotation_weekdays: tuple[int, ...] = ()
    offs_per_week: int = 1
    max_consecutive_days: int = 6
    stretch_limit: int = 125


@dataclass(frozen=True)
class Shift:
    id: str
    name: str
    start_min: int
    end_min: int  # may exceed 1440 for a shift that runs past midnight


@dataclass(frozen=True)
class Brand:
    id: str
    name: str
    pod_id: str | None = None


@dataclass(frozen=True)
class Process:
    id: str
    code: str
    name: str


@dataclass(frozen=True)
class BrandProcess:
    id: str
    brand_id: str
    process_id: str
    shift_id: str
    calendar_type: str = DAILY_EXCEPT_HOLIDAYS
    weekday_mask: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    holidays_closed: bool = True


@dataclass(frozen=True)
class CoverageRule:
    brand_process_id: str
    rule_type: str  # default | weekday | date
    min_staff: int
    weekday: int | None = None
    date: date | None = None
    note: str = ""


@dataclass(frozen=True)
class Allocation:
    id: str
    employee_id: str
    brand_process_id: str
    role: str = PRIMARY
    share: int = 100
    effective_from: date | None = None
    effective_to: date | None = None


@dataclass(frozen=True)
class Leave:
    id: str
    employee_id: str
    leave_type: str  # planned | sick | comp_off | unavailable
    status: str
    start: date
    end: date


@dataclass(frozen=True)
class Preference:
    employee_id: str
    pref_type: str  # off_weekday | off_date | avoid_shift
    weekday: int | None = None
    date: date | None = None
    shift_id: str | None = None
    weight: int = 3


@dataclass(frozen=True)
class Holiday:
    date: date
    name: str


@dataclass(frozen=True)
class HistoryDay:
    """A day from the previous roster, used to carry rules across the month boundary."""
    employee_id: str
    date: date
    status: str
    shift_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
    min_rest_minutes: int = 660  # 11 hours between one shift ending and the next starting
    fairness_spread_warning: int = 3  # Sunday and holiday workdays between most and least loaded


@dataclass
class RosterInput:
    year: int
    month: int
    employees: list[Employee]
    shifts: list[Shift]
    brands: list[Brand]
    processes: list[Process]
    brand_processes: list[BrandProcess]
    coverage_rules: list[CoverageRule] = field(default_factory=list)
    allocations: list[Allocation] = field(default_factory=list)
    leaves: list[Leave] = field(default_factory=list)
    preferences: list[Preference] = field(default_factory=list)
    holidays: list[Holiday] = field(default_factory=list)
    history: list[HistoryDay] = field(default_factory=list)
    comp_off_balances: dict[str, int] = field(default_factory=dict)
    settings: Settings = field(default_factory=Settings)


@dataclass(frozen=True)
class Assignment:
    employee_id: str
    brand_process_id: str
    date: date
    shift_id: str
    is_cover: bool = False
    share: int = 100


@dataclass
class RosterDay:
    employee_id: str
    date: date
    status: str
    source: str = "solver"
    locked: bool = False
    note: str = ""


@dataclass
class Roster:
    days: dict[tuple[str, date], RosterDay] = field(default_factory=dict)
    assignments: list[Assignment] = field(default_factory=list)

    def copy(self) -> "Roster":
        return Roster(
            days={k: replace(v) for k, v in self.days.items()},
            assignments=list(self.assignments),
        )

    def by_employee_day(self) -> dict[tuple[str, date], list[Assignment]]:
        out: dict[tuple[str, date], list[Assignment]] = {}
        for a in self.assignments:
            out.setdefault((a.employee_id, a.date), []).append(a)
        return out

    def by_process_day(self) -> dict[tuple[str, date], list[Assignment]]:
        out: dict[tuple[str, date], list[Assignment]] = {}
        for a in self.assignments:
            out.setdefault((a.brand_process_id, a.date), []).append(a)
        return out


@dataclass
class Issue:
    code: str
    severity: str
    category: str  # coverage | rule | shift | preference | fairness | data | info
    message: str
    date: date | None = None
    employee_id: str | None = None
    brand_process_id: str | None = None
    brand_id: str | None = None
    suggestion: str = ""
    facts: dict = field(default_factory=dict)
    extra_key: str = ""

    @property
    def key(self) -> str:
        """Stable identity, so an override survives re-validation."""
        return ":".join(
            [
                self.code,
                self.date.isoformat() if self.date else "",
                self.employee_id or "",
                self.brand_process_id or "",
                self.extra_key,
            ]
        )
