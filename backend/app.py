"""FastAPI application. The browser only talks to this API."""
from __future__ import annotations

import hmac
import logging
import os

import psycopg
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.db import database as db
from backend.db.database import NotConfigured
from backend.services.rosters import Problem

from backend.routes import rosters, setup

log = logging.getLogger("roster")
app = FastAPI(title="Smart Roster Management System", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(setup.router)
app.include_router(rosters.router)


@app.exception_handler(Problem)
def handle_problem(_: Request, exc: Problem):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


@app.exception_handler(NotConfigured)
def handle_not_configured(_: Request, exc: NotConfigured):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(psycopg.OperationalError)
def handle_database_down(_: Request, exc: psycopg.OperationalError):
    log.error("Database unavailable: %s", type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={"detail": "The database is not reachable. A free Supabase project pauses after a week of low activity; restore it from the Supabase dashboard, then try again."},
    )


@app.get("/api/health")
def health():
    with db.connect() as conn:
        conn.execute("select 1")
    return {"status": "ok"}


@app.get("/api/cron/keepalive")
def keepalive(authorization: str = Header(default="")):
    """Run daily by Vercel cron, so the free Supabase project is not paused."""
    secret = os.getenv("CRON_SECRET", "")
    if secret and not hmac.compare_digest(authorization, f"Bearer {secret}"):
        raise HTTPException(401, "Not authorised.")
    with db.connect() as conn:
        row = db.one(conn, "select count(*) as employees from employees")
    return {"status": "ok", **row}
