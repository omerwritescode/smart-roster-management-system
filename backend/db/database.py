"""Database connection and loading engine inputs from Postgres."""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Iterator
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row

from backend.engine import domain as d


POOLER_PORT = 6543


class NotConfigured(RuntimeError):
    pass


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise NotConfigured("DATABASE_URL is not set. Add it in Vercel's Environment Variables, then redeploy.")
    check_url_shape(url)
    return url


def check_url_shape(url: str) -> None:
    """Catch the common paste mistakes, with a message that says which one it is."""
    fix = "Correct DATABASE_URL in Vercel's Environment Variables, then redeploy."
    if not url.startswith(("postgresql://", "postgres://")):
        raise NotConfigured(f"DATABASE_URL must start with postgresql://. Paste only the string, with no quotes and no 'DATABASE_URL=' in front. {fix}")
    if "[" in url or "]" in url:
        raise NotConfigured(f"DATABASE_URL still contains square brackets. Replace [YOUR-PASSWORD], including the brackets, with your database password. {fix}")
    if url.count("@") > 1:
        raise NotConfigured(f"The password in DATABASE_URL contains an @ symbol, which breaks the connection string. Reset the database password to letters and numbers only. {fix}")
    try:
        parts = urlsplit(url)
        host, port = parts.hostname or "", parts.port
    except ValueError:
        raise NotConfigured(f"DATABASE_URL could not be read, usually because the password contains a symbol such as @ / : or #. Reset the database password to letters and numbers only. {fix}")
    if parts.username is None or parts.password is None or not host:
        raise NotConfigured(f"DATABASE_URL is missing its username, password or host. Copy it again from Connect in Supabase. {fix}")
    if host.startswith("db.") and host.endswith(".supabase.co"):
        raise NotConfigured(f"DATABASE_URL uses Supabase's direct connection, which Vercel cannot reach. In Supabase, click Connect, choose Transaction pooler, and use that string (port {POOLER_PORT}). {fix}")


def describe_connection_failure(text: str) -> str:
    """Turn a driver error into a plain reason. Never includes the connection details."""
    lowered = text.lower()
    if "password authentication failed" in lowered:
        return "Supabase rejected the password in DATABASE_URL. Check it matches your database password, or reset the password in Supabase, then update the variable in Vercel and redeploy."
    if "tenant or user not found" in lowered:
        return "Supabase does not recognise the username or pooler host in DATABASE_URL. Copy the whole Transaction pooler string again from Connect in Supabase, then update the variable in Vercel and redeploy."
    if any(x in lowered for x in ("could not translate host", "failed to resolve host", "name or service not known", "name resolution", "nodename nor servname", "network is unreachable")):
        return "The database host in DATABASE_URL could not be reached. Copy the Transaction pooler string again from Connect in Supabase, then update the variable in Vercel and redeploy."
    if any(x in lowered for x in ("timeout", "timed out")):
        return "The database did not respond in time. Check that the Supabase project is running, and that the pooler string is the current one from Connect."
    if any(x in lowered for x in ("too many", "max client", "remaining connection slots")):
        return "The database has too many open connections right now. Wait a minute and try again."
    return "The database connection failed. The reason is in Vercel's Logs for this request."


def redact(text: str) -> str:
    return re.sub(r"(://[^:/@\s]+:)[^@\s]+@", r"\1***@", text)


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """One short-lived connection per request.

    Serverless functions cannot share a pool, so this relies on Supabase's pooler.
    prepare_threshold=None is required by its transaction mode.
    """
    try:
        conn = psycopg.connect(database_url(), row_factory=dict_row, prepare_threshold=None, connect_timeout=10)
    except psycopg.ProgrammingError:
        raise NotConfigured("DATABASE_URL could not be read. Copy the Transaction pooler string again from Connect in Supabase, then update the variable in Vercel and redeploy.")
    with conn:
        yield conn


def rows(conn: psycopg.Connection, sql: str, params=None) -> list[dict]:
    return conn.execute(sql, params).fetchall()


def one(conn: psycopg.Connection, sql: str, params=None) -> dict | None:
    return conn.execute(sql, params).fetchone()


def insert_many(conn: psycopg.Connection, table: str, columns: list[str], values: list) -> None:
    """Insert rows as multi-row statements.

    psycopg's executemany uses query pipelining, which Supabase's shared pooler does
    not support in transaction mode. This also keeps a save to a few round trips.
    """
    row = "(" + ", ".join(["%s"] * len(columns)) + ")"
    for start in range(0, len(values), 400):
        chunk = values[start:start + 400]
        sql = f"insert into {table} ({', '.join(columns)}) values {', '.join([row] * len(chunk))}"
        conn.execute(sql, [item for entry in chunk for item in entry])


def _minutes(t) -> int:
    return t.hour * 60 + t.minute


def to_shift(row: dict) -> d.Shift:
    start, end = _minutes(row["start_time"]), _minutes(row["end_time"])
    if end <= start:
        end += 1440  # runs past midnight
    return d.Shift(row["id"], row["name"], start, end)


def load_settings(conn) -> d.Settings:
    data = {r["key"]: r["value"] for r in rows(conn, "select key, value from app_settings")}
    return d.Settings(
        min_rest_minutes=int(data.get("min_rest_minutes", 660)),
        fairness_spread_warning=int(data.get("fairness_spread_warning", 3)),
    )


def load_input(conn, year: int, month: int, history_from: dict | None = None) -> d.RosterInput:
    """Everything the engine needs for one month, as engine types."""
    employees = [
        d.Employee(
            id=r["id"], name=r["name"], pod_id=r["pod_id"], title=r["title"],
            weekly_off_policy=r["weekly_off_policy"],
            fixed_off_weekdays=tuple(r["fixed_off_weekdays"] or ()),
            rotation_weekdays=tuple(r["rotation_weekdays"] or ()),
            offs_per_week=r["offs_per_week"], max_consecutive_days=r["max_consecutive_days"],
            stretch_limit=r["stretch_limit"],
        )
        for r in rows(conn, "select * from employees where active order by name")
    ]
    active_brands = rows(conn, "select * from brands where active order by name")
    brand_ids = {b["id"] for b in active_brands}
    bps = [
        d.BrandProcess(
            id=r["id"], brand_id=r["brand_id"], process_id=r["process_id"], shift_id=r["shift_id"],
            calendar_type=r["calendar_type"], weekday_mask=tuple(r["weekday_mask"] or ()),
            holidays_closed=r["holidays_closed"],
        )
        for r in rows(conn, "select * from brand_processes where active")
        if r["brand_id"] in brand_ids
    ]
    bp_ids = {b.id for b in bps}
    first = date(year, month, 1)
    lookback = first - timedelta(days=15)
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

    history: list[d.HistoryDay] = []
    previous = one(
        conn,
        """select id from rosters where month = %s and status = 'published'
           order by version desc limit 1""",
        ((first - timedelta(days=1)).replace(day=1),),
    )
    if previous:
        by_day: dict[tuple[str, date], list[str]] = {}
        for a in rows(conn, "select employee_id, date, shift_id from roster_assignments where roster_id = %s and date >= %s",
                      (previous["id"], lookback)):
            by_day.setdefault((a["employee_id"], a["date"]), []).append(a["shift_id"])
        for r in rows(conn, "select employee_id, date, status from roster_days where roster_id = %s and date >= %s",
                      (previous["id"], lookback)):
            history.append(d.HistoryDay(r["employee_id"], r["date"], r["status"],
                                        tuple(by_day.get((r["employee_id"], r["date"]), ()))))

    return d.RosterInput(
        year=year,
        month=month,
        employees=employees,
        shifts=[to_shift(r) for r in rows(conn, "select * from shifts")],
        brands=[d.Brand(r["id"], r["name"], r["pod_id"]) for r in active_brands],
        processes=[d.Process(r["id"], r["code"], r["name"]) for r in rows(conn, "select * from processes")],
        brand_processes=bps,
        coverage_rules=[
            d.CoverageRule(r["brand_process_id"], r["rule_type"], r["min_staff"], r["weekday"], r["date"], r["note"])
            for r in rows(conn, "select * from coverage_rules") if r["brand_process_id"] in bp_ids
        ],
        allocations=[
            d.Allocation(r["id"], r["employee_id"], r["brand_process_id"], r["role"], r["workload_share"],
                         r["effective_from"], r["effective_to"])
            for r in rows(conn, "select * from allocations") if r["brand_process_id"] in bp_ids
        ],
        leaves=[
            d.Leave(r["id"], r["employee_id"], r["leave_type"], r["status"], r["start_date"], r["end_date"])
            for r in rows(conn, "select * from leaves where end_date >= %s and start_date <= %s", (lookback, last))
        ],
        preferences=[
            d.Preference(r["employee_id"], r["pref_type"], r["weekday"], r["date"], r["shift_id"], r["weight"])
            for r in rows(conn, "select * from preferences")
        ],
        holidays=[d.Holiday(r["date"], r["name"]) for r in rows(conn, "select * from public_holidays")],
        history=history,
        comp_off_balances=comp_off_balances(conn),
        settings=load_settings(conn),
    )


def comp_off_balances(conn) -> dict[str, int]:
    return {
        r["employee_id"]: int(r["balance"])
        for r in rows(conn, "select employee_id, sum(delta) as balance from comp_off_ledger group by employee_id")
    }


def load_roster(conn, roster_id: str) -> d.Roster:
    roster = d.Roster()
    for r in rows(conn, "select * from roster_days where roster_id = %s", (roster_id,)):
        roster.days[(r["employee_id"], r["date"])] = d.RosterDay(
            r["employee_id"], r["date"], r["status"], r["source"], r["locked"], r["note"]
        )
    for a in rows(conn, "select * from roster_assignments where roster_id = %s", (roster_id,)):
        roster.assignments.append(d.Assignment(
            a["employee_id"], a["brand_process_id"], a["date"], a["shift_id"], a["is_cover"], a["share"]
        ))
    return roster


def save_roster_rows(conn, roster_id: str, roster: d.Roster) -> None:
    """Replace a roster's days and assignments."""
    conn.execute("delete from roster_assignments where roster_id = %s", (roster_id,))
    conn.execute("delete from roster_days where roster_id = %s", (roster_id,))
    insert_many(
        conn, "roster_days", ["roster_id", "employee_id", "date", "status", "source", "locked", "note"],
        [(roster_id, r.employee_id, r.date, r.status, r.source, r.locked, r.note) for r in roster.days.values()],
    )
    unique = {(a.employee_id, a.brand_process_id, a.date): a for a in roster.assignments}
    insert_many(
        conn, "roster_assignments", ["roster_id", "employee_id", "brand_process_id", "shift_id", "date", "is_cover", "share"],
        [(roster_id, a.employee_id, a.brand_process_id, a.shift_id, a.date, a.is_cover, a.share) for a in unique.values()],
    )
