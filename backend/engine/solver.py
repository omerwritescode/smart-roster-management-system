"""CP-SAT roster model. Everything solver-specific stays in this module.

Decisions per employee and day: whether it is a weekly off, and which allocated
processes they work. Three tiers of rule:

- Never broken (hard constraints): approved leave, allocation, workload limit,
  shift clashes, rest between shifts, weekly offs, maximum consecutive days.
- Mandatory: minimum coverage, through a slack variable per process and day. The
  model is therefore always feasible, and any slack names the exact day and process.
  Solving runs in two phases: the first minimises total slack, the second fixes that
  total and optimises the rest. This is the "very large penalty" made exact, so no
  preference can ever buy a coverage gap.
- Preferences (small penalties): preferred offs, fair Sundays and holidays, less
  backup use, fewer changes from an existing roster.

Days passed in `locks` become constants, including manual overrides that break a
rule. The solver works around them and the validator flags them.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from ortools.sat.python import cp_model

from . import domain as d
from .calendar import LEAVE_STATUS, Context, eligible_for_weekend_work, rest_minutes, shifts_overlap


@dataclass(frozen=True)
class Weights:
    change: int = 400
    holiday_excess: int = 150
    stretch: int = 120
    backup_use: int = 60
    cross_pod_backup: int = 40
    max_cover_days: int = 30
    preference: int = 20  # multiplied by the preference's own weight (1-5)
    sunday_spread: int = 40
    off_on_holiday: int = 90
    primary_reward: int = 10
    secondary_reward: int = 8


DEFAULT_WEIGHTS = Weights()


@dataclass
class SolveOptions:
    weights: Weights = field(default_factory=lambda: DEFAULT_WEIGHTS)
    time_limit: float | None = None
    workers: int | None = None
    locks: dict[tuple[str, date], tuple[str, tuple[str, ...], str]] = field(default_factory=dict)
    baseline: d.Roster | None = None
    seed: int = 7


@dataclass
class SolveResult:
    roster: d.Roster
    status: str
    objective: float
    wall_time: float
    uncovered: dict[tuple[str, date], int]
    fewest_gaps_proved: bool = False  # True when no roster under the hard rules can have fewer gaps


class SolverError(RuntimeError):
    pass


def solve(inp: d.RosterInput, options: SolveOptions | None = None) -> SolveResult:
    opts = options or SolveOptions()
    ctx = Context(inp)
    w = opts.weights
    model = cp_model.CpModel()
    started = time.perf_counter()

    assign: dict[tuple[str, str, date], cp_model.IntVar] = {}
    off: dict[tuple[str, date], cp_model.IntVar] = {}
    work: dict[tuple[str, date], cp_model.IntVar] = {}
    stretch: dict[tuple[str, date], cp_model.IntVar] = {}
    objective: list = []
    offset = 0  # constant part of the objective, reported in the score only

    locked_assign: dict[tuple[str, date], tuple[str, ...]] = {}
    locked_status: dict[tuple[str, date], str] = {}
    for (emp, day), (status, bps, _note) in opts.locks.items():
        locked_status[(emp, day)] = status
        locked_assign[(emp, day)] = bps if status == d.WORK else ()

    # ------------------------------------------------------------ decision variables
    for e in ctx.employees.values():
        for day in ctx.days:
            key = (e.id, day)
            if key in locked_status or key in ctx.blocked:
                continue
            off[key] = model.NewBoolVar(f"off_{e.id}_{day}")
            todays = []
            for a in ctx.employee_allocations(e.id, day):
                if ctx.required(a.brand_process_id, day) <= 0:
                    continue
                var = model.NewBoolVar(f"a_{e.id}_{a.brand_process_id}_{day}")
                assign[(e.id, a.brand_process_id, day)] = var
                model.Add(var + off[key] <= 1)
                todays.append((a, var))
            if not todays:
                continue
            work[key] = model.NewBoolVar(f"w_{e.id}_{day}")
            model.AddMaxEquality(work[key], [v for _, v in todays])

            # Workload: 100% normally, up to the stretch limit on a day with cover work.
            covers = [v for a, v in todays if a.role == d.BACKUP]
            load = sum(a.share * v for a, v in todays)
            if covers and e.stretch_limit > d.FULL_DAY:
                stretch[key] = model.NewBoolVar(f"st_{e.id}_{day}")
                model.Add(stretch[key] <= sum(covers))
                model.Add(load <= d.FULL_DAY + (e.stretch_limit - d.FULL_DAY) * stretch[key])
                objective.append(w.stretch * stretch[key])
            else:
                model.Add(load <= d.FULL_DAY)

            # Different shifts with overlapping hours cannot be worked on one day.
            for i in range(len(todays)):
                for j in range(i + 1, len(todays)):
                    s1 = ctx.shifts[ctx.bps[todays[i][0].brand_process_id].shift_id]
                    s2 = ctx.shifts[ctx.bps[todays[j][0].brand_process_id].shift_id]
                    if shifts_overlap(s1, s2):
                        model.Add(todays[i][1] + todays[j][1] <= 1)

    # ------------------------------------------------------------ rest between days
    minimum_rest = inp.settings.min_rest_minutes

    def shifts_on(emp_id: str, day: date):
        """Pairs of (shift, variable or None when the day is fixed)."""
        pairs = []
        if (emp_id, day) in locked_status:
            for bp in locked_assign.get((emp_id, day), ()):
                pairs.append((ctx.shifts[ctx.bps[bp].shift_id], None))
        elif day < ctx.first_day:
            hist = ctx.history.get((emp_id, day))
            for s in hist.shift_ids if hist else ():
                if s in ctx.shifts:
                    pairs.append((ctx.shifts[s], None))
        else:
            for a in ctx.employee_allocations(emp_id, day):
                var = assign.get((emp_id, a.brand_process_id, day))
                if var is not None:
                    pairs.append((ctx.shifts[ctx.bps[a.brand_process_id].shift_id], var))
        return pairs

    for e in ctx.employees.values():
        for day in ctx.days:
            yesterday = day - timedelta(days=1)
            for s1, v1 in shifts_on(e.id, yesterday):
                for s2, v2 in shifts_on(e.id, day):
                    if rest_minutes(s1, s2) >= minimum_rest:
                        continue
                    if v1 is None and v2 is None:
                        continue
                    if v1 is None:
                        model.Add(v2 == 0)
                    elif v2 is None:
                        model.Add(v1 == 0)
                    else:
                        model.Add(v1 + v2 <= 1)

    # ------------------------------------------------------------ weekly offs
    for e in ctx.employees.values():
        for monday, days in ctx.weeks():
            need = ctx.week_need(e, monday, days)
            locked_offs = sum(1 for x in days if locked_status.get((e.id, x)) == d.WEEKLY_OFF)
            free = [x for x in days if (e.id, x) in off]
            if need.allowed is not None:
                allowed = set(need.allowed)
                for x in free:
                    model.Add(off[(e.id, x)] == (1 if x in allowed else 0))
            else:
                total = sum(off[(e.id, x)] for x in free)
                model.Add(total <= max(0, need.upper - locked_offs))
                minimum = min(max(0, need.need - locked_offs), len(free))
                if minimum > 0:
                    model.Add(total >= minimum)

    # ------------------------------------------------------------ consecutive days
    def work_term(emp_id: str, day: date):
        """(variable or None, constant worked)."""
        if day < ctx.first_day:
            hist = ctx.history.get((emp_id, day))
            return None, 1 if hist and hist.status == d.WORK else 0
        if (emp_id, day) in locked_status:
            return None, 1 if locked_status[(emp_id, day)] == d.WORK else 0
        return work.get((emp_id, day)), 0

    for e in ctx.employees.values():
        size = e.max_consecutive_days + 1
        start = ctx.first_day - timedelta(days=e.max_consecutive_days)
        cursor = start
        while cursor + timedelta(days=size - 1) <= ctx.last_day:
            variables, fixed = [], 0
            for i in range(size):
                var, constant = work_term(e.id, cursor + timedelta(days=i))
                fixed += constant
                if var is not None:
                    variables.append(var)
            if variables and fixed <= e.max_consecutive_days:
                model.Add(sum(variables) + fixed <= e.max_consecutive_days)
            cursor += timedelta(days=1)

    # ------------------------------------------------------------ coverage
    slack: dict[tuple[str, date], cp_model.IntVar] = {}
    for bp in ctx.bps.values():
        for day in ctx.days:
            required = ctx.required(bp.id, day)
            if required <= 0:
                continue
            variables = [
                assign[(a.employee_id, bp.id, day)]
                for a in ctx.process_allocations(bp.id, day)
                if (a.employee_id, bp.id, day) in assign
            ]
            fixed = sum(
                1 for (emp, x), bps in locked_assign.items() if x == day and bp.id in bps
            )
            gap = model.NewIntVar(0, required, f"gap_{bp.id}_{day}")
            slack[(bp.id, day)] = gap
            model.Add(sum(variables) + fixed + gap >= required)
            if day in ctx.holidays:
                # Holiday work costs someone a holiday: staff to the minimum only.
                excess = model.NewIntVar(0, len(variables) + fixed, f"hx_{bp.id}_{day}")
                model.Add(sum(variables) + fixed - required <= excess)
                objective.append(w.holiday_excess * excess)

    # ------------------------------------------------------------ backups and rewards
    cover_terms: dict[str, list] = {}
    for (emp_id, bp_id, day), var in assign.items():
        alloc = ctx.allocation_for(emp_id, bp_id, day)
        employee = ctx.employees[emp_id]
        brand = ctx.brands.get(ctx.bps[bp_id].brand_id)
        if alloc.role == d.BACKUP:
            cost = w.backup_use
            if brand and brand.pod_id != employee.pod_id:
                cost += w.cross_pod_backup
            objective.append(cost * var)
            cover_terms.setdefault(emp_id, []).append(var)
        elif day not in ctx.holidays:
            reward = w.primary_reward if alloc.role == d.PRIMARY else w.secondary_reward
            objective.append(-reward * var)
    if cover_terms and w.max_cover_days:
        peak = model.NewIntVar(0, len(ctx.days) * 10, "peak_cover")
        for terms in cover_terms.values():
            model.Add(sum(terms) <= peak)
        objective.append(w.max_cover_days * peak)

    # ------------------------------------------------------------ preferences
    for p in inp.preferences:
        e = ctx.employees.get(p.employee_id)
        if e is None:
            continue
        cost = w.preference * p.weight
        if p.pref_type == "off_date" and p.date:
            var = off.get((e.id, p.date))
            if var is not None:
                objective.append(-cost * var)
        elif p.pref_type == "off_weekday" and p.weekday is not None:
            for _, days in ctx.weeks():
                for x in days:
                    if x.weekday() == p.weekday and (e.id, x) in off:
                        objective.append(-cost * off[(e.id, x)])
        elif p.pref_type == "avoid_shift" and p.shift_id:
            for (emp_id, bp_id, _), var in assign.items():
                if emp_id == e.id and ctx.bps[bp_id].shift_id == p.shift_id:
                    objective.append(cost * var)

    # ------------------------------------------------------------ Sunday and holiday fairness
    for (emp_id, day), var in off.items():
        if day in ctx.holidays:
            objective.append(w.off_on_holiday * var)
    if w.sunday_spread:
        counts = []
        for e in ctx.employees.values():
            if not eligible_for_weekend_work(ctx, e.id):
                continue
            terms = []
            fixed = 0
            for day in ctx.days:
                if day.weekday() != d.SUNDAY and day not in ctx.holidays:
                    continue
                var, constant = work_term(e.id, day)
                fixed += constant
                if var is not None:
                    terms.append(var)
            counts.append(sum(terms) + fixed)
        if len(counts) >= 2:
            top = model.NewIntVar(0, len(ctx.days), "sun_top")
            bottom = model.NewIntVar(0, len(ctx.days), "sun_bottom")
            for c in counts:
                model.Add(c <= top)
                model.Add(c >= bottom)
            objective.append(w.sunday_spread * (top - bottom))

    # ------------------------------------------------------------ fewer changes
    if opts.baseline is not None:
        base_days = opts.baseline.days
        base_assign = {(a.employee_id, a.brand_process_id, a.date) for a in opts.baseline.assignments}
        for key, var in assign.items():
            if key in base_assign:
                objective.append(w.change * (1 - var))
            else:
                objective.append(w.change * var)
        for (emp_id, day), var in off.items():
            was_off = base_days.get((emp_id, day)) is not None and base_days[(emp_id, day)].status == d.WEEKLY_OFF
            objective.append(w.change * (1 - var) if was_off else w.change * var)

    solver = cp_model.CpSolver()
    limit = opts.time_limit if opts.time_limit is not None else float(os.getenv("SOLVER_TIME_LIMIT", "18"))
    workers = opts.workers or int(os.getenv("SOLVER_WORKERS", "4"))

    # Phase 1: find the fewest coverage gaps any roster can achieve under the hard rules.
    gap_total = sum(slack.values()) if slack else 0
    fewest_proved = True
    fewest = 0
    if slack:
        model.Minimize(gap_total)
        solver.parameters.max_time_in_seconds = max(1.0, limit * 0.4)
        solver.parameters.num_workers = workers
        solver.parameters.random_seed = opts.seed
        first = solver.Solve(model)
        if first not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise SolverError(
                f"The solver found no roster within {limit:.0f} seconds (status: {solver.StatusName(first)}). "
                "No roster was saved. Try again, or raise SOLVER_TIME_LIMIT."
            )
        fewest = int(solver.ObjectiveValue())
        fewest_proved = first == cp_model.OPTIMAL
        for index in range(len(model.Proto().variables)):
            var = model.GetIntVarFromProtoIndex(index)
            model.AddHint(var, solver.Value(var))
        model.Add(gap_total <= fewest)  # coverage is now fixed: preferences cannot trade it away

    # Phase 2: within that coverage, spend the remaining freedom on the softer aims.
    model.Minimize(sum(objective))
    solver.parameters.max_time_in_seconds = max(2.0, limit - (time.perf_counter() - started))
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = opts.seed
    solver.parameters.relative_gap_limit = 0.01
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SolverError(
            f"The solver found no roster within {limit:.0f} seconds (status: {solver.StatusName(status)}). "
            "No roster was saved. Try again, or raise SOLVER_TIME_LIMIT."
        )

    # ------------------------------------------------------------ read the answer
    roster = d.Roster()
    for e in ctx.employees.values():
        for day in ctx.days:
            key = (e.id, day)
            if key in locked_status:
                _, bps, note = opts.locks[key]
                # Frozen past days stay as they were. Only a person's edit stays marked as locked.
                base = opts.baseline.days.get(key) if opts.baseline else None
                roster.days[key] = d.RosterDay(
                    e.id, day, locked_status[key], source=base.source if base else "manual",
                    locked=base.locked if base else True, note=note,
                )
                for bp_id in locked_assign[key]:
                    roster.assignments.append(_make_assignment(ctx, e.id, bp_id, day))
                continue
            chosen = [
                a.brand_process_id for a in ctx.employee_allocations(e.id, day)
                if (var := assign.get((e.id, a.brand_process_id, day))) is not None and solver.Value(var)
            ]
            if key in ctx.blocked:
                status_name = LEAVE_STATUS[ctx.blocked[key]]
            elif solver.Value(off[key]):
                status_name = d.WEEKLY_OFF
            elif chosen:
                status_name = d.WORK
            elif day in ctx.holidays:
                status_name = d.HOLIDAY
            else:
                status_name = d.IDLE
            roster.days[key] = d.RosterDay(e.id, day, status_name)
            for bp_id in chosen:
                roster.assignments.append(_make_assignment(ctx, e.id, bp_id, day))

    uncovered = {k: solver.Value(v) for k, v in slack.items() if solver.Value(v) > 0}
    return SolveResult(
        roster=roster,
        status=solver.StatusName(status),
        objective=solver.ObjectiveValue(),
        wall_time=time.perf_counter() - started,
        uncovered=uncovered,
        fewest_gaps_proved=fewest_proved,
    )


def _make_assignment(ctx: Context, emp_id: str, bp_id: str, day: date) -> d.Assignment:
    alloc = ctx.allocation_for(emp_id, bp_id, day)
    return d.Assignment(
        employee_id=emp_id,
        brand_process_id=bp_id,
        date=day,
        shift_id=ctx.bps[bp_id].shift_id,
        is_cover=alloc.role == d.BACKUP if alloc else True,
        share=alloc.share if alloc else 25,
    )
