"""Roster endpoints. Solving happens outside any database transaction, because a
connection held for 20 seconds would be wasted on a small free pooler."""
from __future__ import annotations

import os
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.db import database as db
from backend.engine import advisor, domain as d, plans
from backend.engine import repair as repair_engine
from backend.engine.calendar import Context
from backend.engine.solver import SolverError
from backend.engine.validator import validate
from backend.services import ai, exports
from backend.services import rosters as svc

from .deps import Actor, current_actor, require_manager, require_ops

router = APIRouter(prefix="/api")


def _solver_guard(call):
    try:
        return call()
    except SolverError as exc:
        raise svc.Problem(str(exc), 503)


class GenerateIn(BaseModel):
    month: str
    plan: str = "coverage_first"


class CompareIn(BaseModel):
    month: str


class EditIn(BaseModel):
    edits: list[dict] = Field(min_length=1, max_length=40)
    reason: str = ""


class RepairIn(BaseModel):
    change_from: date | None = None


class OverrideIn(BaseModel):
    key: str
    reason: str


class RemoveOverrideIn(BaseModel):
    key: str


class DecisionIn(BaseModel):
    pod_id: str | None = None
    approve: bool = True
    note: str = ""


class ExplainIn(BaseModel):
    key: str


class LeaveIn(BaseModel):
    employee_id: str
    leave_type: str
    start_date: date
    end_date: date
    reason: str = ""
    status: str = "pending"


class LeaveDecisionIn(BaseModel):
    status: str
    regenerate: bool = True
    roster_id: str | None = None  # the version on screen; defaults to the latest active one


# ---------------------------------------------------------------- reading
@router.get("/plans")
def plan_list():
    return [{"id": k, "label": v["label"], "description": v["description"]} for k, v in plans.PLANS.items()]


@router.get("/rosters")
def list_rosters(month: str | None = None):
    with db.connect() as conn:
        if month:
            y, m = svc.parse_month(month)
            return db.rows(conn, """select id, month, version, status, plan_label, parent_id, score, metrics, solver, summary, created_by, created_at, published_at
                                    from rosters where month = %s order by version desc""", (date(y, m, 1),))
        return db.rows(conn, """select id, month, version, status, plan_label, parent_id, score, metrics, solver, summary, created_by, created_at, published_at
                                from rosters order by month desc, version desc limit 60""")


@router.get("/rosters/{roster_id}")
def get_roster(roster_id: str):
    with db.connect() as conn:
        row, inp, roster, _ = svc.refresh(conn, roster_id)
        return svc.serialise(conn, row, inp, roster)


@router.get("/rosters/{roster_id}/diff/{other_id}")
def roster_diff(roster_id: str, other_id: str):
    """What changes going from other_id to roster_id."""
    with db.connect() as conn:
        row = svc.get_roster_row(conn, roster_id)
        inp = svc.input_for(conn, row)
        changes = repair_engine.diff(db.load_roster(conn, other_id), db.load_roster(conn, roster_id))
        return svc.named_changes(inp, changes)


# ---------------------------------------------------------------- generating
@router.post("/rosters/generate")
def generate(body: GenerateIn, actor: Actor = Depends(require_ops)):
    year, month = svc.parse_month(body.month)
    if body.plan not in plans.PLANS:
        raise svc.Problem("Choose one of the listed plans.")
    with db.connect() as conn:
        inp = db.load_input(conn, year, month)
    if not inp.employees or not inp.brand_processes:
        raise svc.Problem("Add at least one employee and one brand process before generating.")
    result = _solver_guard(lambda: plans.generate(inp, body.plan))
    with db.connect() as conn:
        issues = validate(inp, result.roster)
        metric = plans.metrics(inp, result.roster, issues)
        summary = svc.describe_generation(metric["gap_slots"], result.fewest_gaps_proved)
        roster_id = svc.create_roster(conn, inp, result.roster, plan=body.plan, parent=None, summary=summary,
                                      actor=actor.as_dict(), solver_info=svc.solver_info(result))
        svc.audit(conn, actor.as_dict(), "generate", "roster", roster_id, {"plan": body.plan, "metrics": metric})
        return {"roster_id": roster_id, "metrics": metric, "summary": summary, "solver": svc.solver_info(result)}


@router.post("/rosters/compare")
def compare_plans(body: CompareIn, actor: Actor = Depends(require_ops)):
    """Solve every plan for a month, and save each as a draft to compare side by side."""
    year, month = svc.parse_month(body.month)
    with db.connect() as conn:
        inp = db.load_input(conn, year, month)
    if not inp.employees or not inp.brand_processes:
        raise svc.Problem("Add at least one employee and one brand process before generating.")
    limit = float(os.getenv("SOLVER_COMPARE_TIME_LIMIT", "12"))
    solved = {plan: _solver_guard(lambda p=plan: plans.generate(inp, p, time_limit=limit)) for plan in plans.PLANS}
    out = []
    with db.connect() as conn:
        for plan, result in solved.items():
            issues = validate(inp, result.roster)
            metric = plans.metrics(inp, result.roster, issues)
            summary = svc.describe_generation(metric["gap_slots"], result.fewest_gaps_proved)
            roster_id = svc.create_roster(conn, inp, result.roster, plan=plan, parent=None, summary=summary,
                                          actor=actor.as_dict(), solver_info=svc.solver_info(result))
            out.append({"roster_id": roster_id, "plan": plan, "label": plans.PLANS[plan]["label"],
                        "description": plans.PLANS[plan]["description"], "metrics": metric, "summary": summary})
        svc.audit(conn, actor.as_dict(), "compare_plans", "month", body.month, {"plans": [o["plan"] for o in out]})
    return out


# ---------------------------------------------------------------- editing
@router.post("/rosters/{roster_id}/preview")
def preview(roster_id: str, body: EditIn):
    """Live validation: what would this edit break or fix? Nothing is saved."""
    with db.connect() as conn:
        return svc.preview_edits(conn, roster_id, body.edits)


@router.post("/rosters/{roster_id}/edit")
def edit(roster_id: str, body: EditIn, actor: Actor = Depends(require_manager)):
    with db.connect() as conn:
        return svc.save_edits(conn, roster_id, body.edits, actor.as_dict(), body.reason)


@router.post("/rosters/{roster_id}/override")
def override(roster_id: str, body: OverrideIn, actor: Actor = Depends(require_ops)):
    with db.connect() as conn:
        svc.override_issue(conn, roster_id, body.key, body.reason, actor.as_dict())
        return {"ok": True}


@router.post("/rosters/{roster_id}/override/remove")
def remove_override(roster_id: str, body: RemoveOverrideIn, actor: Actor = Depends(require_ops)):
    with db.connect() as conn:
        svc.remove_override(conn, roster_id, body.key, actor.as_dict())
        return {"ok": True}


@router.post("/rosters/{roster_id}/explain")
def explain(roster_id: str, body: ExplainIn):
    with db.connect() as conn:
        issue = db.one(conn, "select * from issues where roster_id = %s and key = %s", (roster_id, body.key))
        if issue is None:
            raise HTTPException(404, "That issue is no longer on this roster. It may already be resolved.")
        return ai.explain(conn, issue)


@router.get("/rosters/{roster_id}/recommend")
def recommend(roster_id: str, brand_process_id: str, day: date = Query(alias="date")):
    with db.connect() as conn:
        row = svc.get_roster_row(conn, roster_id)
        inp = svc.input_for(conn, row)
        roster = db.load_roster(conn, roster_id)
    if brand_process_id not in Context(inp).bps:
        raise svc.Problem("That process is no longer active.", 404)
    return advisor.recommend(inp, roster, brand_process_id, day)


# ---------------------------------------------------------------- handling change
@router.post("/rosters/{roster_id}/repair")
def repair(roster_id: str, body: RepairIn, actor: Actor = Depends(require_ops)):
    """Regenerate from a date onwards with minimal changes. Produces a new draft to review."""
    with db.connect() as conn:
        row = svc.get_roster_row(conn, roster_id)
        inp = svc.input_for(conn, row)
        base = db.load_roster(conn, roster_id)
    change_from = body.change_from or date(inp.year, inp.month, 1)
    result, changes = _solver_guard(lambda: svc.build_repair(row, inp, base, change_from))
    with db.connect() as conn:
        summary = f"Regenerated from {change_from.isoformat()}: {len(changes)} day(s) changed from version {row['version']}."
        new_id = svc.create_roster(conn, inp, result.roster, plan=row["plan_label"], parent=roster_id, summary=summary,
                                   actor=actor.as_dict(), solver_info=svc.solver_info(result), inherit_overrides_from=roster_id)
        svc.audit(conn, actor.as_dict(), "repair", "roster", new_id, {"from": change_from, "changes": len(changes)})
        return {"roster_id": new_id, "changes": svc.named_changes(inp, changes), "summary": summary}


def _base_roster(conn, month: date, roster_id: str | None) -> dict | None:
    """The version a change acts on: the one on screen when it is for this month."""
    if roster_id:
        row = db.one(conn, "select * from rosters where id = %s and month = %s and status <> 'superseded'", (roster_id, month))
        if row:
            return row
    return svc.latest_active_roster(conn, month)


def _impact_for_absence(conn, employee_id: str, start: date, end: date, leave_type: str, month: date, roster_id: str | None = None) -> dict | None:
    row = _base_roster(conn, month, roster_id)
    if row is None:
        return None
    inp = svc.input_for(conn, row)
    roster = db.load_roster(conn, row["id"])
    clipped_start = max(start, month)
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    clipped_end = min(end, next_month - timedelta(days=1))
    if clipped_start > clipped_end:
        return None
    trial = repair_engine.absence_preview(inp, roster, employee_id, clipped_start, clipped_end, leave_type)
    impact = advisor.employee_impact(inp, roster, trial)
    ctx = Context(inp)
    gaps = [i for i in impact["introduced"] if i.category == "coverage" and i.severity == d.BLOCKER]
    still_met = []
    for a in ctx.allocs_by_employee.get(employee_id, []):
        if a.role == d.BACKUP:
            continue
        cursor = clipped_start
        while cursor <= clipped_end:
            required = ctx.required(a.brand_process_id, cursor)
            if required > 0 and not any(g.brand_process_id == a.brand_process_id and g.date == cursor for g in gaps):
                staffed = {x.employee_id for x in trial.by_process_day().get((a.brand_process_id, cursor), [])}
                if roster.days.get((employee_id, cursor)) and roster.days[(employee_id, cursor)].status == d.WORK:
                    still_met.append({"process": ctx.bp_label(a.brand_process_id), "date": cursor.isoformat(), "required": required, "staffed": len(staffed)})
            cursor += timedelta(days=1)
    return {
        "roster_id": row["id"], "version": row["version"], "status": row["status"],
        "employee": ctx.employee_name(employee_id),
        "gap_count": len(gaps), "brands_affected": impact["brands_affected"],
        "gaps": [svc.issue_dict(i) for i in gaps],
        "other_new_issues": [svc.issue_dict(i) for i in impact["introduced"] if i not in gaps and i.severity != d.INFO],
        "coverage_still_met": still_met,
    }


@router.get("/impact/absence")
def absence_impact(employee_id: str, start: date, end: date, leave_type: str = "unavailable", roster_id: str | None = None):
    """If this person were away: which brands lose coverage, and which hold?"""
    if leave_type not in ("planned", "sick", "comp_off", "unavailable"):
        raise svc.Problem("Choose a leave type from the list.")
    with db.connect() as conn:
        result = _impact_for_absence(conn, employee_id, start, end, leave_type, start.replace(day=1), roster_id)
    if result is None:
        raise svc.Problem("There is no roster for that month yet. Generate one first.", 404)
    return result


@router.post("/leaves")
def create_leave(body: LeaveIn, actor: Actor = Depends(current_actor)):
    if body.end_date < body.start_date:
        raise svc.Problem("The end date is before the start date.", 422)
    if body.leave_type not in ("planned", "sick", "comp_off", "unavailable"):
        raise svc.Problem("Choose a leave type from the list.", 422)
    with db.connect() as conn:
        row = db.one(
            conn,
            """insert into leaves (employee_id, leave_type, status, start_date, end_date, reason)
               values (%s, %s, 'pending', %s, %s, %s) returning *""",
            (body.employee_id, body.leave_type, body.start_date, body.end_date, body.reason),
        )
        svc.audit(conn, actor.as_dict(), "request_leave", "leave", row["id"], {"employee": body.employee_id})
        return row


@router.delete("/leaves/{leave_id}")
def delete_leave(leave_id: str, actor: Actor = Depends(require_manager)):
    with db.connect() as conn:
        conn.execute("delete from leaves where id = %s", (leave_id,))
        svc.audit(conn, actor.as_dict(), "delete_leave", "leave", leave_id)
        return {"deleted": True}


@router.post("/leaves/{leave_id}/decision")
def decide_leave(leave_id: str, body: LeaveDecisionIn, actor: Actor = Depends(require_manager)):
    """Approving leave regenerates the roster as a draft, with minimal changes, for a person to approve."""
    if body.status not in ("approved", "rejected", "pending"):
        raise svc.Problem("Choose approved or rejected.")
    with db.connect() as conn:
        leave = db.one(conn, "select * from leaves where id = %s", (leave_id,))
        if leave is None:
            raise svc.Problem("That request no longer exists.", 404)
        was = leave["status"]
        conn.execute("update leaves set status = %s, decided_by = %s, decided_at = now() where id = %s",
                     (body.status, actor.name, leave_id))
        if leave["leave_type"] == "comp_off":
            conn.execute("delete from comp_off_ledger where leave_id = %s", (leave_id,))
            if body.status == "approved":
                span = (leave["end_date"] - leave["start_date"]).days + 1
                conn.execute(
                    "insert into comp_off_ledger (employee_id, delta, entry_date, reason, leave_id) values (%s, %s, %s, 'Comp-off taken', %s)",
                    (leave["employee_id"], -span, leave["start_date"], leave_id),
                )
        svc.audit(conn, actor.as_dict(), f"leave_{body.status}", "leave", leave_id, {"was": was})
        month = leave["start_date"].replace(day=1)
        base_row = _base_roster(conn, month, body.roster_id)
        if not body.regenerate or base_row is None or was == body.status or (was != "approved" and body.status != "approved"):
            return {"status": body.status, "regenerated": False}
        inp = svc.input_for(conn, base_row)
        base = db.load_roster(conn, base_row["id"])
    # Outside the transaction: solving takes seconds.
    result, changes = _solver_guard(lambda: svc.build_repair(base_row, inp, base, leave["start_date"]))
    with db.connect() as conn:
        summary = (f"Regenerated after {body.status} {leave['leave_type'].replace('_', '-')} for "
                   f"{Context(inp).employee_name(leave['employee_id'])}: {len(changes)} day(s) changed from version {base_row['version']}.")
        new_id = svc.create_roster(conn, inp, result.roster, plan=base_row["plan_label"], parent=base_row["id"], summary=summary,
                                   actor=actor.as_dict(), solver_info=svc.solver_info(result), inherit_overrides_from=base_row["id"])
        svc.audit(conn, actor.as_dict(), "auto_regenerate", "roster", new_id, {"leave": leave_id, "changes": len(changes)})
        svc.notify(conn, new_id, None, "draft_ready", f"New draft ready after a leave decision: version {svc.get_roster_row(conn, new_id)['version']}", summary)
        return {"status": body.status, "regenerated": True, "roster_id": new_id, "summary": summary,
                "changes": svc.named_changes(inp, changes), "based_on_version": base_row["version"]}


# ---------------------------------------------------------------- workflow
@router.post("/rosters/{roster_id}/submit")
def submit(roster_id: str, actor: Actor = Depends(require_ops)):
    with db.connect() as conn:
        svc.submit(conn, roster_id, actor.as_dict())
        return {"status": "pod_review"}


@router.post("/rosters/{roster_id}/pod-decision")
def pod_decision(roster_id: str, body: DecisionIn, actor: Actor = Depends(require_manager)):
    if not body.pod_id:
        raise svc.Problem("Choose the pod this decision is for.")
    with db.connect() as conn:
        return svc.pod_decision(conn, roster_id, body.pod_id, body.approve, body.note, actor.as_dict())


@router.post("/rosters/{roster_id}/ops-reject")
def ops_reject(roster_id: str, body: DecisionIn, actor: Actor = Depends(require_ops)):
    with db.connect() as conn:
        svc.reject_ops(conn, roster_id, body.note, actor.as_dict())
        return {"status": "draft"}


@router.post("/rosters/{roster_id}/publish")
def publish(roster_id: str, actor: Actor = Depends(require_ops)):
    with db.connect() as conn:
        result = svc.publish(conn, roster_id, actor.as_dict())
    # After the commit, so a webhook never announces a publish that did not save.
    svc.send_webhook(result.pop("webhook"))
    return result


# ---------------------------------------------------------------- exports
@router.get("/rosters/{roster_id}/export.csv")
def export_csv(roster_id: str):
    with db.connect() as conn:
        row = svc.get_roster_row(conn, roster_id)
        inp = svc.input_for(conn, row)
        roster = db.load_roster(conn, roster_id)
        pods = svc.pods_of_roster(conn)
    name = f"roster-{row['month'].strftime('%Y-%m')}-v{row['version']}.csv"
    return Response(exports.csv_export(inp, roster, pods), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/rosters/{roster_id}/export.xlsx")
def export_xlsx(roster_id: str):
    with db.connect() as conn:
        row, inp, roster, _ = svc.refresh(conn, roster_id)
        issues = svc.issue_rows(conn, roster_id)
        pods = svc.pods_of_roster(conn)
    meta = {"month": row["month"].strftime("%B %Y"), "version": row["version"], "status": row["status"]}
    name = f"roster-{row['month'].strftime('%Y-%m')}-v{row['version']}.xlsx"
    return Response(exports.excel_export(inp, roster, issues, pods, meta),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- activity
@router.get("/notifications")
def notifications(employee_id: str | None = None, limit: int = Query(default=60, le=200)):
    with db.connect() as conn:
        if employee_id:
            return db.rows(conn, "select * from notifications where employee_id = %s or employee_id is null order by created_at desc, id desc limit %s", (employee_id, limit))
        return db.rows(conn, "select * from notifications order by created_at desc, id desc limit %s", (limit,))


@router.post("/notifications/read")
def mark_read(employee_id: str | None = None):
    with db.connect() as conn:
        if employee_id:
            conn.execute("update notifications set read_at = now() where read_at is null and (employee_id = %s or employee_id is null)", (employee_id,))
        else:
            conn.execute("update notifications set read_at = now() where read_at is null")
        return {"ok": True}


@router.get("/audit")
def audit_log(limit: int = Query(default=100, le=300)):
    with db.connect() as conn:
        return db.rows(conn, "select * from audit_log order by created_at desc, id desc limit %s", (limit,))


@router.get("/comp-offs/{employee_id}")
def comp_offs(employee_id: str):
    with db.connect() as conn:
        return db.rows(conn, "select * from comp_off_ledger where employee_id = %s order by entry_date desc, id desc", (employee_id,))

