"""Add, edit and remove the things a roster is built from. No code changes needed."""
from __future__ import annotations

import json
import datetime as dt
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError, create_model

from backend.db import database as db
from backend.db import seed
from backend.services import rosters as svc

from .deps import Actor, current_actor, require_ops

router = APIRouter(prefix="/api")
Weekday = Annotated[int, Field(ge=0, le=6)]
Name = Annotated[str, Field(min_length=1, max_length=120)]


class PodIn(BaseModel):
    name: Name
    lead_employee_id: str | None = None


class EmployeeIn(BaseModel):
    name: Name
    title: str = "Associate"
    pod_id: str | None = None
    weekly_off_policy: Literal["solver", "fixed", "rotating"] = "solver"
    fixed_off_weekdays: list[Weekday] = []
    rotation_weekdays: list[Weekday] = []
    offs_per_week: int = Field(1, ge=0, le=3)
    max_consecutive_days: int = Field(6, ge=1, le=14)
    stretch_limit: int = Field(125, ge=100, le=200)
    active: bool = True


class BrandIn(BaseModel):
    name: Name
    pod_id: str | None = None
    notes: str = ""
    active: bool = True


class ProcessIn(BaseModel):
    code: Annotated[str, Field(min_length=1, max_length=8)]
    name: Name


class ShiftIn(BaseModel):
    name: Name
    start_time: dt.time
    end_time: dt.time


class HolidayIn(BaseModel):
    date: dt.date
    name: Name
    kind: Literal["public", "company"] = "public"


class BrandProcessIn(BaseModel):
    brand_id: str
    process_id: str
    calendar_type: Literal["all_days", "daily_except_holidays", "sundays_holidays_off", "custom"] = "daily_except_holidays"
    weekday_mask: list[Weekday] = [0, 1, 2, 3, 4, 5, 6]
    holidays_closed: bool = True
    shift_id: str
    active: bool = True


class CoverageRuleIn(BaseModel):
    brand_process_id: str
    rule_type: Literal["default", "weekday", "date"]
    weekday: Weekday | None = None
    date: dt.date | None = None
    min_staff: int = Field(ge=0, le=50)
    note: str = ""


class AllocationIn(BaseModel):
    employee_id: str
    brand_process_id: str
    role: Literal["primary", "secondary", "backup"] = "primary"
    workload_share: int = Field(100, ge=1, le=200)
    effective_from: dt.date | None = None
    effective_to: dt.date | None = None


class PreferenceIn(BaseModel):
    employee_id: str
    pref_type: Literal["off_weekday", "off_date", "avoid_shift"]
    weekday: Weekday | None = None
    date: dt.date | None = None
    shift_id: str | None = None
    weight: int = Field(3, ge=1, le=5)


# Table name -> (input model, whether an employee may use it, sort order)
ENTITIES: dict[str, tuple[type[BaseModel], str]] = {
    "pods": (PodIn, "name"),
    "employees": (EmployeeIn, "name"),
    "brands": (BrandIn, "name"),
    "processes": (ProcessIn, "code"),
    "shifts": (ShiftIn, "start_time"),
    "public_holidays": (HolidayIn, "date"),
    "brand_processes": (BrandProcessIn, "id"),
    "coverage_rules": (CoverageRuleIn, "id"),
    "allocations": (AllocationIn, "id"),
    "preferences": (PreferenceIn, "id"),
}
PLAIN_NAMES = {
    "pods": "pod", "employees": "employee", "brands": "brand", "processes": "process", "shifts": "shift",
    "public_holidays": "holiday", "brand_processes": "brand process", "coverage_rules": "coverage rule",
    "allocations": "allocation", "preferences": "preference",
}


def _model(entity: str, partial: bool = False) -> type[BaseModel]:
    if entity not in ENTITIES:
        raise HTTPException(404, "That setup list does not exist.")
    model = ENTITIES[entity][0]
    if not partial:
        return model
    fields: dict[str, Any] = {n: (f.annotation | None, None) for n, f in model.model_fields.items()}
    return create_model(f"{model.__name__}Partial", **fields)


def _parse(model: type[BaseModel], body: dict) -> dict:
    try:
        return model.model_validate(body).model_dump(exclude_unset=True)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(x) for x in first["loc"])
        raise HTTPException(422, f"{field.replace('_', ' ').title()}: {first['msg']}.")


def _friendly(exc: psycopg.Error, entity: str) -> HTTPException:
    name = PLAIN_NAMES.get(entity, "record")
    if isinstance(exc, psycopg.errors.UniqueViolation):
        return HTTPException(409, f"That {name} already exists. Edit the existing one instead.")
    if isinstance(exc, psycopg.errors.ForeignKeyViolation):
        return HTTPException(409, f"This {name} is still in use elsewhere. Remove what depends on it first.")
    if isinstance(exc, psycopg.errors.CheckViolation):
        return HTTPException(422, f"Those values are not valid for a {name}. Check the type and the fields it needs.")
    return HTTPException(400, f"The {name} could not be saved.")


def _check_rule_shape(entity: str, data: dict) -> None:
    """Keep rules complete, with messages the form can show as they are."""
    if entity == "coverage_rules":
        kind = data.get("rule_type")
        if kind == "weekday" and data.get("weekday") is None:
            raise HTTPException(422, "Choose a weekday for this rule.")
        if kind == "date" and data.get("date") is None:
            raise HTTPException(422, "Choose a date for this rule.")
        if kind in ("default", "weekday"):
            data["date"] = None
        if kind in ("default", "date"):
            data["weekday"] = None
    if entity == "preferences":
        kind = data.get("pref_type")
        needs = {"off_weekday": "weekday", "off_date": "date", "avoid_shift": "shift_id"}.get(kind)
        if needs and data.get(needs) is None:
            raise HTTPException(422, f"Choose a {needs.replace('_id', '')} for this preference.")
    if entity == "employees":
        if data.get("weekly_off_policy") == "fixed" and not data.get("fixed_off_weekdays"):
            raise HTTPException(422, "A fixed weekly off needs at least one weekday.")
        if data.get("weekly_off_policy") == "rotating" and not data.get("rotation_weekdays"):
            raise HTTPException(422, "A rotating weekly off needs at least one weekday.")


@router.get("/bootstrap")
def bootstrap():
    """Everything the screens need to show names and setup, in one call."""
    with db.connect() as conn:
        data = {name: db.rows(conn, f"select * from {name} order by {order}") for name, (_, order) in ENTITIES.items()}
        data["leaves"] = db.rows(conn, "select * from leaves order by start_date, created_at")
        data["settings"] = {r["key"]: r["value"] for r in db.rows(conn, "select key, value from app_settings")}
        data["comp_off_balances"] = db.comp_off_balances(conn)
        data["comp_off_ledger"] = db.rows(conn, "select * from comp_off_ledger order by entry_date desc, id desc limit 200")
        return data


@router.post("/setup/{entity}")
def create(entity: str, body: dict, actor: Actor = Depends(current_actor)):
    model = _model(entity)
    if entity != "preferences":
        require_ops(actor)
    data = _parse(model, body)
    full = model.model_validate(body).model_dump()
    _check_rule_shape(entity, full)
    if entity == "coverage_rules":
        data = full  # the shape check clears fields that do not apply to this rule type
    columns = list(data)
    placeholders = ", ".join(["%s"] * len(columns))
    with db.connect() as conn:
        try:
            row = db.one(conn, f"insert into {entity} ({', '.join(columns)}) values ({placeholders}) returning *", [data[c] for c in columns])
        except psycopg.Error as exc:
            raise _friendly(exc, entity)
        svc.audit(conn, actor.as_dict(), f"create_{PLAIN_NAMES[entity].replace(' ', '_')}", entity, row["id"], data)
        return row


@router.patch("/setup/{entity}/{row_id}")
def update(entity: str, row_id: str, body: dict, actor: Actor = Depends(current_actor)):
    model = _model(entity, partial=True)
    if entity != "preferences":
        require_ops(actor)
    data = _parse(model, body)
    if not data:
        raise HTTPException(400, "Nothing to change.")
    with db.connect() as conn:
        current = db.one(conn, f"select * from {entity} where id = %s", (row_id,))
        if current is None:
            raise HTTPException(404, f"That {PLAIN_NAMES[entity]} no longer exists. Refresh the page.")
        merged = {**current, **data}
        _check_rule_shape(entity, merged)
        if entity == "coverage_rules":
            data["date"], data["weekday"] = merged["date"], merged["weekday"]
        assignments = ", ".join(f"{c} = %s" for c in data)
        try:
            row = db.one(conn, f"update {entity} set {assignments} where id = %s returning *", [*data.values(), row_id])
        except psycopg.Error as exc:
            raise _friendly(exc, entity)
        svc.audit(conn, actor.as_dict(), f"update_{PLAIN_NAMES[entity].replace(' ', '_')}", entity, row_id, data)
        return row


@router.delete("/setup/{entity}/{row_id}")
def remove(entity: str, row_id: str, actor: Actor = Depends(current_actor)):
    _model(entity)
    if entity != "preferences":
        require_ops(actor)
    with db.connect() as conn:
        try:
            result = conn.execute(f"delete from {entity} where id = %s", (row_id,))
        except psycopg.Error as exc:
            raise _friendly(exc, entity)
        if result.rowcount == 0:
            raise HTTPException(404, f"That {PLAIN_NAMES[entity]} no longer exists. Refresh the page.")
        svc.audit(conn, actor.as_dict(), f"delete_{PLAIN_NAMES[entity].replace(' ', '_')}", entity, row_id)
        return {"deleted": True}


class SettingsIn(BaseModel):
    min_rest_minutes: int | None = Field(None, ge=0, le=1440)
    fairness_spread_warning: int | None = Field(None, ge=1, le=31)


@router.put("/settings")
def save_settings(body: SettingsIn, actor: Actor = Depends(require_ops)):
    with db.connect() as conn:
        for key, value in body.model_dump(exclude_none=True).items():
            conn.execute(
                "insert into app_settings (key, value) values (%s, %s) on conflict (key) do update set value = excluded.value",
                (key, json.dumps(value)),
            )
        svc.audit(conn, actor.as_dict(), "update_settings", "settings", None, body.model_dump(exclude_none=True))
        return {r["key"]: r["value"] for r in db.rows(conn, "select key, value from app_settings")}


@router.post("/demo/reset")
def reset_demo(actor: Actor = Depends(current_actor)):
    """Restore the sample data. Open to every role, so a reviewer can always start clean."""
    with db.connect() as conn:
        result = seed.reset(conn)
        svc.audit(conn, actor.as_dict(), "reset_demo_data", "demo", None, result)
        return result
