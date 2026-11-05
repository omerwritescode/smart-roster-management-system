"""The role switcher. This is a demo convenience and not security: see the README."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

ROLES = {"ops_manager": "Operations manager", "pod_lead": "Pod lead", "employee": "Employee"}


@dataclass
class Actor:
    role: str
    name: str
    pod_id: str | None = None
    employee_id: str | None = None

    def as_dict(self) -> dict:
        return {"role": self.role, "name": self.name, "pod_id": self.pod_id, "employee_id": self.employee_id}


def current_actor(
    x_role: str = Header(default="ops_manager"),
    x_actor_name: str = Header(default=""),
    x_pod_id: str = Header(default=""),
    x_employee_id: str = Header(default=""),
) -> Actor:
    if x_role not in ROLES:
        raise HTTPException(400, "Unknown role. Choose a role from the switcher.")
    return Actor(role=x_role, name=(x_actor_name or ROLES[x_role])[:80], pod_id=x_pod_id or None, employee_id=x_employee_id or None)


def require_ops(actor: Actor = Depends(current_actor)) -> Actor:
    if actor.role != "ops_manager":
        raise HTTPException(403, "Only the operations manager can do this. Switch role to continue.")
    return actor


def require_manager(actor: Actor = Depends(current_actor)) -> Actor:
    if actor.role not in ("ops_manager", "pod_lead"):
        raise HTTPException(403, "Only an operations manager or pod lead can do this. Switch role to continue.")
    return actor
