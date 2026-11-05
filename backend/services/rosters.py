"""Roster lifecycle: generate, validate, edit, repair, approve, publish."""
from __future__ import annotations

import json
import logging
import os
from datetime import date

import httpx

from backend.db import database as db
from backend.engine import domain as d
from backend.engine import plans, repair as repair_engine
from backend.engine.calendar import Context
from backend.engine.validator import comp_off_entitlements, fmt, validate

log = logging.getLogger("roster.service")
EDITABLE = {"draft", "pod_review", "ops_review"}
KEEP_UNPUBLISHED_PER_MONTH = 25


class Problem(Exception):
    """A user-facing failure, with a message that says what to do."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def parse_month(text: str) -> tuple[int, int]:
    try:
        year, month = text.split("-")[:2]
        result = (int(year), int(month))
        date(result[0], result[1], 1)
    except (ValueError, AttributeError):
        raise Problem("Month must look like 2026-12.")
    return result


def audit(conn, actor: dict, action: str, entity: str, entity_id: str | None, details: dict | None = None) -> None:
    conn.execute(
        "insert into audit_log (actor, role, action, entity, entity_id, details) values (%s, %s, %s, %s, %s, %s)",
        (actor["name"], actor["role"], action, entity, entity_id, json.dumps(details or {}, default=str)),
    )


def next_version(conn, month: date) -> int:
    row = db.one(conn, "select coalesce(max(version), 0) + 1 as v from rosters where month = %s", (month,))
    return row["v"]


def get_roster_row(conn, roster_id: str) -> dict:
    row = db.one(conn, "select * from rosters where id = %s", (roster_id,))
    if row is None:
        raise Problem("That roster no longer exists. Refresh the page.", 404)
    return row


def input_for(conn, row: dict) -> d.RosterInput:
    return db.load_input(conn, row["month"].year, row["month"].month)


# ---------------------------------------------------------------- saving and issues
def store_issues(conn, roster_id: str, issues: list[d.Issue]) -> None:
    conn.execute("delete from issues where roster_id = %s", (roster_id,))
    unique = {i.key: i for i in issues}
    db.insert_many(
        conn, "issues",
        ["roster_id", "key", "code", "severity", "category", "date", "employee_id", "brand_process_id", "brand_id", "message", "suggestion", "facts"],
        [
            (roster_id, i.key, i.code, i.severity, i.category, i.date, i.employee_id, i.brand_process_id,
             i.brand_id, i.message, i.suggestion, json.dumps(i.facts, default=str))
            for i in unique.values()
        ],
    )


def create_roster(conn, inp: d.RosterInput, roster: d.Roster, *, plan: str, parent: str | None, summary: str,
                  actor: dict, solver_info: dict | None = None, inherit_overrides_from: str | None = None) -> str:
    month = date(inp.year, inp.month, 1)
    version = next_version(conn, month)
    issues = validate(inp, roster)
    metric = plans.metrics(inp, roster, issues)
    row = db.one(
        conn,
        """insert into rosters (month, version, plan_label, parent_id, score, metrics, solver, summary, created_by)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
        (month, version, plan, parent, metric["score"], json.dumps(metric), json.dumps(solver_info or {}), summary, actor["name"]),
    )
    roster_id = row["id"]
    db.save_roster_rows(conn, roster_id, roster)
    store_issues(conn, roster_id, issues)
    if inherit_overrides_from:
        keys = {i.key for i in issues}
        for o in db.rows(conn, "select * from issue_overrides where roster_id = %s", (inherit_overrides_from,)):
            if o["key"] in keys:
                conn.execute(
                    "insert into issue_overrides (roster_id, key, reason, overridden_by) values (%s, %s, %s, %s)",
                    (roster_id, o["key"], o["reason"], o["overridden_by"]),
                )
    _prune(conn, month)
    return roster_id


def _prune(conn, month: date) -> None:
    """Free database limits are small, and anyone can click Generate on a public demo."""
    conn.execute(
        """delete from rosters where id in (
             select id from rosters where month = %s and status in ('draft','rejected')
             order by created_at desc offset %s)""",
        (month, KEEP_UNPUBLISHED_PER_MONTH),
    )


def solver_info(result) -> dict:
    return {
        "status": result.status,
        "seconds": round(result.wall_time, 1),
        "fewest_gaps_proved": result.fewest_gaps_proved,
        "uncovered_slots": sum(result.uncovered.values()),
    }


def describe_generation(metric_gaps: int, proved: bool) -> str:
    if metric_gaps == 0:
        return "Every required day is covered."
    tail = " The solver proved no roster can have fewer under the mandatory rules." if proved else ""
    return f"{metric_gaps} required staffing slot(s) cannot be filled.{tail}"


def refresh(conn, roster_id: str) -> tuple[dict, d.RosterInput, d.Roster, list[d.Issue]]:
    """Re-run the validator against current setup, so a rule change shows up immediately."""
    row = get_roster_row(conn, roster_id)
    inp = input_for(conn, row)
    roster = db.load_roster(conn, roster_id)
    issues = validate(inp, roster)
    stored = {r["key"] for r in db.rows(conn, "select key from issues where roster_id = %s", (roster_id,))}
    if stored != {i.key for i in issues}:
        store_issues(conn, roster_id, issues)
        metric = plans.metrics(inp, roster, issues)
        conn.execute("update rosters set metrics = %s, score = %s where id = %s",
                     (json.dumps(metric), metric["score"], roster_id))
        row = {**row, "metrics": metric, "score": metric["score"]}
    return row, inp, roster, issues


def issue_rows(conn, roster_id: str) -> list[dict]:
    return db.rows(
        conn,
        """select i.*, o.reason as override_reason, o.overridden_by, o.overridden_at
           from issues i left join issue_overrides o on o.roster_id = i.roster_id and o.key = i.key
           where i.roster_id = %s
           order by case i.severity when 'blocker' then 0 when 'warning' then 1 else 2 end, i.date nulls last, i.code""",
        (roster_id,),
    )


def unresolved_blockers(conn, roster_id: str) -> list[dict]:
    return [i for i in issue_rows(conn, roster_id) if i["severity"] == "blocker" and not i["override_reason"]]


def coverage_grid(ctx: Context, roster: d.Roster) -> list[dict]:
    """For every process and day: required, staffed, and who."""
    by_bp_day = roster.by_process_day()
    out = []
    for bp in ctx.bps.values():
        for day in ctx.days:
            required = ctx.required(bp.id, day)
            people = sorted({a.employee_id for a in by_bp_day.get((bp.id, day), [])})
            if required > 0 or people:
                out.append({"brand_process_id": bp.id, "date": day.isoformat(), "required": required, "staffed": len(people), "employees": people})
    return out


def serialise(conn, row: dict, inp: d.RosterInput, roster: d.Roster) -> dict:
    ctx = Context(inp)
    return {
        "roster": row,
        "days": [
            {"employee_id": r.employee_id, "date": r.date.isoformat(), "status": r.status, "source": r.source,
             "locked": r.locked, "note": r.note}
            for r in roster.days.values()
        ],
        "assignments": [
            {"employee_id": a.employee_id, "brand_process_id": a.brand_process_id, "date": a.date.isoformat(),
             "shift_id": a.shift_id, "is_cover": a.is_cover, "share": a.share}
            for a in roster.assignments
        ],
        "coverage": coverage_grid(ctx, roster),
        "issues": issue_rows(conn, row["id"]),
        "approvals": db.rows(conn, "select * from approvals where roster_id = %s order by created_at", (row["id"],)),
        "holidays": [{"date": h.date.isoformat(), "name": h.name} for h in inp.holidays if ctx.first_day <= h.date <= ctx.last_day],
        "days_in_month": [x.isoformat() for x in ctx.days],
    }


# ---------------------------------------------------------------- manual edits
def edits_from_payload(payload: list[dict]) -> list[repair_engine.DayEdit]:
    edits = []
    for e in payload:
        try:
            edits.append(repair_engine.DayEdit(
                employee_id=e["employee_id"], date=date.fromisoformat(e["date"]), status=e["status"],
                bp_ids=tuple(e.get("bp_ids") or ()),
            ))
        except (KeyError, ValueError) as exc:
            raise Problem(f"That edit is incomplete: {exc}")
    return edits


def with_added_backups(inp: d.RosterInput, payload: list[dict]) -> d.RosterInput:
    extra = []
    for e in payload:
        bp_id = e.get("add_backup_allocation")
        if bp_id:
            extra.append(d.Allocation(f"preview-{e['employee_id']}-{bp_id}", e["employee_id"], bp_id, d.BACKUP, 25))
    if not extra:
        return inp
    return d.RosterInput(**{**inp.__dict__, "allocations": [*inp.allocations, *extra]})


def apply_edits(inp, roster, edits) -> d.Roster:
    Context(inp)  # surfaces bad input early
    current = roster
    for edit in edits:
        if edit.status not in d.ALL_STATUSES:
            raise Problem(f"Unknown day status: {edit.status}")
        if (edit.employee_id, edit.date) not in current.days:
            raise Problem("That employee or date is not part of this roster.")
        current = repair_engine.apply_edit(inp, current, edit)
    return current


def issue_dict(i: d.Issue) -> dict:
    return {"key": i.key, "code": i.code, "severity": i.severity, "category": i.category, "message": i.message,
            "suggestion": i.suggestion, "date": i.date.isoformat() if i.date else None,
            "employee_id": i.employee_id, "brand_process_id": i.brand_process_id, "facts": i.facts}


def preview_edits(conn, roster_id: str, payload: list[dict]) -> dict:
    row, inp, roster, before = refresh(conn, roster_id)
    trial_inp = with_added_backups(inp, payload)
    after_roster = apply_edits(trial_inp, roster, edits_from_payload(payload))
    after = validate(trial_inp, after_roster)
    old, new = {i.key: i for i in before}, {i.key: i for i in after}
    def visible(i):
        return i.severity != d.INFO
    return {
        "resolved": [issue_dict(old[k]) for k in old if k not in new and visible(old[k])],
        "introduced": [issue_dict(new[k]) for k in new if k not in old and visible(new[k])],
        "blockers_before": sum(1 for i in before if i.severity == d.BLOCKER),
        "blockers_after": sum(1 for i in after if i.severity == d.BLOCKER),
        "earns_comp_off": sorted(
            {x.isoformat() for (e, x), r in after_roster.days.items() if r.note == d.NOTE_WORKED_WEEKLY_OFF}
            - {x.isoformat() for (e, x), r in roster.days.items() if r.note == d.NOTE_WORKED_WEEKLY_OFF}
        ),
    }


def save_edits(conn, roster_id: str, payload: list[dict], actor: dict, reason: str = "") -> dict:
    """Apply edits. Editing a published roster creates a new draft version."""
    row, inp, roster, _ = refresh(conn, roster_id)
    if row["status"] == "superseded":
        raise Problem("This version has been replaced. Open the latest version to change it.")
    for e in payload:
        bp_id = e.get("add_backup_allocation")
        if bp_id:
            conn.execute(
                """insert into allocations (employee_id, brand_process_id, role, workload_share)
                   select %s, %s, 'backup', 25
                   where not exists (select 1 from allocations where employee_id = %s and brand_process_id = %s)""",
                (e["employee_id"], bp_id, e["employee_id"], bp_id),
            )
    inp = input_for(conn, row)
    new_roster = apply_edits(inp, roster, edits_from_payload(payload))
    changes = repair_engine.diff(roster, new_roster)

    if row["status"] in EDITABLE and row["status"] != "draft":
        conn.execute("update rosters set status = 'draft' where id = %s", (roster_id,))
        conn.execute("delete from approvals where roster_id = %s and stage = 'pod_review'", (roster_id,))
    if row["status"] == "published" or row["status"] == "rejected":
        new_id = create_roster(conn, inp, new_roster, plan=row["plan_label"], parent=roster_id,
                               summary=f"Manual change to version {row['version']}", actor=actor,
                               inherit_overrides_from=roster_id)
        audit(conn, actor, "edit_creates_version", "roster", new_id, {"changes": changes, "reason": reason})
        return {"roster_id": new_id, "new_version": True, "changes": changes}

    db.save_roster_rows(conn, roster_id, new_roster)
    issues = validate(inp, new_roster)
    store_issues(conn, roster_id, issues)
    metric = plans.metrics(inp, new_roster, issues)
    conn.execute("update rosters set metrics = %s, score = %s where id = %s", (json.dumps(metric), metric["score"], roster_id))
    audit(conn, actor, "manual_edit", "roster", roster_id, {"changes": changes, "reason": reason})
    return {"roster_id": roster_id, "new_version": False, "changes": changes}


def clear_locks(conn, roster_id: str, actor: dict) -> None:
    conn.execute("update roster_days set locked = false where roster_id = %s", (roster_id,))
    audit(conn, actor, "clear_locks", "roster", roster_id)


# ---------------------------------------------------------------- overrides
def override_issue(conn, roster_id: str, key: str, reason: str, actor: dict) -> None:
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise Problem("Write a reason of at least 5 characters. It stays on the record with this override.")
    issue = db.one(conn, "select * from issues where roster_id = %s and key = %s", (roster_id, key))
    if issue is None:
        raise Problem("That issue is no longer on this roster. It may already be resolved.", 404)
    if issue["severity"] != "blocker":
        raise Problem("Only blockers need an override. Warnings do not stop publishing.")
    conn.execute(
        """insert into issue_overrides (roster_id, key, reason, overridden_by) values (%s, %s, %s, %s)
           on conflict (roster_id, key) do update set reason = excluded.reason, overridden_by = excluded.overridden_by, overridden_at = now()""",
        (roster_id, key, reason, actor["name"]),
    )
    audit(conn, actor, "override_blocker", "issue", key, {"roster_id": roster_id, "reason": reason, "message": issue["message"]})


def remove_override(conn, roster_id: str, key: str, actor: dict) -> None:
    conn.execute("delete from issue_overrides where roster_id = %s and key = %s", (roster_id, key))
    audit(conn, actor, "remove_override", "issue", key, {"roster_id": roster_id})


# ---------------------------------------------------------------- repair
def latest_active_roster(conn, month: date) -> dict | None:
    """The roster a change should act on: the newest draft or in-review version, then the published one."""
    return db.one(
        conn,
        """select * from rosters where month = %s and status in ('published','draft','pod_review','ops_review')
           order by case when status = 'published' then 1 else 0 end, version desc limit 1""",
        (month,),
    )


def build_repair(row: dict, inp: d.RosterInput, base: d.Roster, change_from: date, time_limit: float | None = None):
    change_from = max(change_from, date(inp.year, inp.month, 1))
    result = repair_engine.repair(inp, base, change_from, plan=row["plan_label"], time_limit=time_limit)
    return result, repair_engine.diff(base, result.roster)


def named_changes(inp: d.RosterInput, changes: list[dict]) -> list[dict]:
    ctx = Context(inp)
    return [
        {**c, "employee": ctx.employee_name(c["employee_id"]),
         "from_labels": [ctx.bp_label(x) for x in c["from_processes"]],
         "to_labels": [ctx.bp_label(x) for x in c["to_processes"]]}
        for c in changes
    ]


# ---------------------------------------------------------------- workflow
def pods_of_roster(conn) -> list[dict]:
    return db.rows(conn, "select id, name, lead_employee_id from pods order by name")


def submit(conn, roster_id: str, actor: dict) -> None:
    row = get_roster_row(conn, roster_id)
    if row["status"] != "draft":
        raise Problem("Only a draft can be sent for review.")
    conn.execute("update rosters set status = 'pod_review' where id = %s", (roster_id,))
    conn.execute("delete from approvals where roster_id = %s and stage <> 'publish'", (roster_id,))
    conn.execute("insert into approvals (roster_id, stage, actor, decision) values (%s, 'pod_review', %s, 'submitted')", (roster_id, actor["name"]))
    audit(conn, actor, "submit_for_review", "roster", roster_id)
    notify(conn, roster_id, None, "review_requested", f"Version {row['version']} is ready for pod lead review", "")


def pod_decision(conn, roster_id: str, pod_id: str, approve: bool, note: str, actor: dict) -> dict:
    row = get_roster_row(conn, roster_id)
    if row["status"] != "pod_review":
        raise Problem("This roster is not waiting for pod lead review.")
    pod = db.one(conn, "select * from pods where id = %s", (pod_id,))
    if pod is None:
        raise Problem("That pod no longer exists.", 404)
    if actor["role"] == "pod_lead" and actor.get("pod_id") != pod_id:
        raise Problem(f"Only the {pod['name']} pod lead can decide for this pod.", 403)
    if actor["role"] == "ops_manager" and len((note or "").strip()) < 5:
        raise Problem("Add a short note when approving on a pod lead's behalf.")
    if not approve and len((note or "").strip()) < 5:
        raise Problem("Say what needs to change, so the operations manager can act on it.")
    conn.execute("delete from approvals where roster_id = %s and stage = 'pod_review' and pod_id = %s", (roster_id, pod_id))
    conn.execute(
        "insert into approvals (roster_id, stage, pod_id, actor, decision, note) values (%s, 'pod_review', %s, %s, %s, %s)",
        (roster_id, pod_id, actor["name"], "approved" if approve else "rejected", note or ""),
    )
    audit(conn, actor, "pod_approved" if approve else "pod_rejected", "roster", roster_id, {"pod_id": pod_id, "note": note})
    if not approve:
        conn.execute("update rosters set status = 'draft' where id = %s", (roster_id,))
        notify(conn, roster_id, None, "changes_requested", f"{pod['name']} pod requested changes to version {row['version']}", note or "")
        return {"status": "draft"}
    approved = {
        r["pod_id"] for r in db.rows(
            conn, "select pod_id from approvals where roster_id = %s and stage = 'pod_review' and decision = 'approved'", (roster_id,))
    }
    all_pods = {p["id"] for p in pods_of_roster(conn)}
    if all_pods <= approved:
        conn.execute("update rosters set status = 'ops_review' where id = %s", (roster_id,))
        notify(conn, roster_id, None, "ops_review", f"All pod leads approved version {row['version']}", "Ready for operations approval.")
        return {"status": "ops_review"}
    return {"status": "pod_review", "waiting_for": sorted(all_pods - approved)}


def reject_ops(conn, roster_id: str, note: str, actor: dict) -> None:
    row = get_roster_row(conn, roster_id)
    if row["status"] != "ops_review":
        raise Problem("This roster is not waiting for operations approval.")
    if len((note or "").strip()) < 5:
        raise Problem("Say what needs to change before sending it back.")
    conn.execute("update rosters set status = 'draft' where id = %s", (roster_id,))
    conn.execute("insert into approvals (roster_id, stage, actor, decision, note) values (%s, 'ops_review', %s, 'rejected', %s)", (roster_id, actor["name"], note))
    audit(conn, actor, "ops_rejected", "roster", roster_id, {"note": note})


def publish(conn, roster_id: str, actor: dict) -> dict:
    """Blockers stop this unless each has a written override. Only a person can publish."""
    row, inp, roster, _ = refresh(conn, roster_id)
    if row["status"] != "ops_review":
        raise Problem("A roster must pass pod lead review before it can be published.")
    remaining = unresolved_blockers(conn, roster_id)
    if remaining:
        raise Problem(f"{len(remaining)} blocker(s) still need a fix or a written override before publishing.", 409)

    previous = db.one(conn, "select id, version from rosters where month = %s and status = 'published' order by version desc limit 1", (row["month"],))
    conn.execute("update rosters set status = 'published', published_at = now() where id = %s", (roster_id,))
    conn.execute("insert into approvals (roster_id, stage, actor, decision) values (%s, 'publish', %s, 'published')", (roster_id, actor["name"]))
    if previous:
        conn.execute("update rosters set status = 'superseded' where id = %s", (previous["id"],))

    earned = _sync_comp_offs(conn, inp, roster, roster_id, row["month"])
    audit(conn, actor, "publish", "roster", roster_id, {"version": row["version"], "comp_offs_earned": earned})

    month_name = row["month"].strftime("%B %Y")
    change_list: list[dict] = []
    if previous:
        change_list = repair_engine.diff(db.load_roster(conn, previous["id"]), roster)
        _notify_changes(conn, inp, roster_id, row, change_list, month_name)
    else:
        notify(conn, roster_id, None, "published", f"{month_name} roster published (version {row['version']})",
               "Everyone's schedule for the month is now live.")
    webhook = {
        "event": "roster.published", "roster_id": roster_id, "month": row["month"].isoformat(), "version": row["version"],
        "replaces_version": previous["version"] if previous else None, "changes": named_changes(inp, change_list),
    }
    return {"status": "published", "changes": len(change_list), "comp_offs_earned": earned, "webhook": webhook}


def _sync_comp_offs(conn, inp, roster, roster_id, month) -> int:
    """The ledger follows the latest published roster, so an undone day earns nothing."""
    next_month = (month.replace(day=28).toordinal() + 4)
    month_end = date.fromordinal(next_month).replace(day=1)
    conn.execute(
        "delete from comp_off_ledger where delta > 0 and roster_id is not null and entry_date >= %s and entry_date < %s",
        (month, month_end),
    )
    earned = comp_off_entitlements(inp, roster)
    db.insert_many(
        conn, "comp_off_ledger", ["employee_id", "delta", "entry_date", "reason", "roster_id"],
        [(emp, 1, day, reason, roster_id) for emp, day, reason in earned],
    )
    return len(earned)


def _notify_changes(conn, inp, roster_id, row, changes, month_name) -> None:
    ctx = Context(inp)
    by_person: dict[str, list[dict]] = {}
    for c in changes:
        by_person.setdefault(c["employee_id"], []).append(c)
    notify(conn, roster_id, None, "roster_changed",
           f"{month_name} roster changed: version {row['version']} is now live",
           f"{len(changes)} day(s) changed for {len(by_person)} employee(s).")
    for emp_id, items in by_person.items():
        if emp_id not in ctx.employees:
            continue
        lines = []
        for c in items[:6]:
            day = date.fromisoformat(c["date"])
            lines.append(f"{fmt(day)}: {describe_day(ctx, c['from_status'], c['from_processes'])} to {describe_day(ctx, c['to_status'], c['to_processes'])}")
        if len(items) > 6:
            lines.append(f"and {len(items) - 6} more")
        notify(conn, roster_id, emp_id, "schedule_changed", f"Your schedule changed on {len(items)} day(s)", "; ".join(lines), {"changes": items})


def describe_day(ctx: Context, status: str | None, bps: list[str]) -> str:
    if status == d.WORK:
        return ", ".join(ctx.bp_label(b) for b in bps) or "working"
    return (status or "nothing").replace("_", " ")


def notify(conn, roster_id, employee_id, kind, title, body, payload=None) -> None:
    conn.execute(
        "insert into notifications (roster_id, employee_id, kind, title, body, payload) values (%s, %s, %s, %s, %s, %s)",
        (roster_id, employee_id, kind, title, body, json.dumps(payload or {}, default=str)),
    )


def send_webhook(payload: dict) -> bool:
    """Optional outbound hook, for example an n8n workflow that sends messages. Best effort."""
    url = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()
    if not url:
        return False
    try:
        return httpx.post(url, json=payload, timeout=6).is_success
    except httpx.HTTPError as exc:
        log.warning("Webhook failed: %s", type(exc).__name__)
        return False
