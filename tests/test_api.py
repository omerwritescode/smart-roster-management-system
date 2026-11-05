"""The whole system through its API, against a real Postgres database.

Set TEST_DATABASE_URL to run these. They are skipped otherwise.
"""
import csv
import io
import os

import httpx
import pytest

TEST_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL is not set")
OPS = {"X-Role": "ops_manager", "X-Actor-Name": "Test Ops"}


@pytest.fixture(scope="module")
def client():
    os.environ["DATABASE_URL"] = TEST_URL
    os.environ["SOLVER_TIME_LIMIT"] = "4"
    os.environ["SOLVER_COMPARE_TIME_LIMIT"] = "3"
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("NOTIFY_WEBHOOK_URL", None)
    import psycopg
    from fastapi.testclient import TestClient

    def no_pipelining(self):
        raise AssertionError("Supabase's shared pooler does not support query pipelining in transaction mode")

    psycopg.Connection.pipeline = no_pipelining  # executemany would use this, and fail once deployed

    from backend.app import app
    from backend.db.migrate import run

    run(fresh=True, url=TEST_URL)
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean(client):
    assert client.post("/api/demo/reset", headers=OPS).status_code == 200


def generate(client, month="2026-12", plan="coverage_first"):
    r = client.post("/api/rosters/generate", json={"month": month, "plan": plan}, headers=OPS)
    assert r.status_code == 200, r.text
    return r.json()["roster_id"]


def detail(client, roster_id):
    r = client.get(f"/api/rosters/{roster_id}")
    assert r.status_code == 200, r.text
    return r.json()


def pass_reviews(client, roster_id):
    assert client.post(f"/api/rosters/{roster_id}/submit", headers=OPS).status_code == 200
    pods = client.get("/api/bootstrap").json()["pods"]
    for pod in pods:
        r = client.post(f"/api/rosters/{roster_id}/pod-decision", json={"pod_id": pod["id"], "approve": True},
                        headers={"X-Role": "pod_lead", "X-Pod-Id": pod["id"], "X-Actor-Name": "Lead"})
        assert r.status_code == 200, r.text


def override_all(client, roster_id):
    for i in detail(client, roster_id)["issues"]:
        if i["severity"] == "blocker":
            r = client.post(f"/api/rosters/{roster_id}/override", json={"key": i["key"], "reason": "Client accepted this gap"}, headers=OPS)
            assert r.status_code == 200, r.text


def publish_flow(client, roster_id):
    override_all(client, roster_id)
    pass_reviews(client, roster_id)
    r = client.post(f"/api/rosters/{roster_id}/publish", headers=OPS)
    assert r.status_code == 200, r.text
    return r.json()


def test_generate_shows_everyone_and_names_gaps(client):
    d = detail(client, generate(client))
    assert len(d["days"]) == 34 * 31
    assert len(d["days_in_month"]) == 31
    blockers = [i for i in d["issues"] if i["severity"] == "blocker"]
    assert blockers and all(i["category"] == "coverage" for i in blockers)
    assert d["roster"]["metrics"]["gap_slots"] == sum(i["facts"]["short_by"] for i in blockers)
    assert d["roster"]["solver"]["fewest_gaps_proved"] is True
    short = [c for c in d["coverage"] if c["staffed"] < c["required"]]
    assert {(c["brand_process_id"], c["date"]) for c in short} == {(i["brand_process_id"], i["date"]) for i in blockers}
    closed_sunday = [c for c in d["coverage"] if c["brand_process_id"] == "lotus-cs" and c["date"] == "2026-12-06"]
    assert closed_sunday == []  # Little Lotus closes on Sundays, and needs nobody


def test_preview_changes_nothing_and_edit_is_revalidated(client):
    roster_id = generate(client)
    d = detail(client, roster_id)
    day = next(x for x in d["days"] if x["employee_id"] == "emp-karan" and x["status"] == "work")
    edit = {"employee_id": "emp-karan", "date": day["date"], "status": "unavailable", "bp_ids": []}
    preview = client.post(f"/api/rosters/{roster_id}/preview", json={"edits": [edit]}).json()
    assert any(i["brand_process_id"] == "haldi-cs" or i["brand_process_id"] == "haldi-ret" for i in preview["introduced"])
    assert preview["blockers_after"] > preview["blockers_before"]
    assert detail(client, roster_id)["roster"]["metrics"] == d["roster"]["metrics"]
    saved = client.post(f"/api/rosters/{roster_id}/edit", json={"edits": [edit], "reason": "Test"}, headers=OPS).json()
    assert saved["new_version"] is False and len(saved["changes"]) == 1
    after = detail(client, roster_id)
    assert after["roster"]["metrics"]["blockers"] == preview["blockers_after"]
    rec = next(x for x in after["days"] if x["employee_id"] == "emp-karan" and x["date"] == day["date"])
    assert rec["status"] == "unavailable" and rec["locked"] and rec["source"] == "manual"


def test_bad_edit_is_rejected_with_a_clear_message(client):
    roster_id = generate(client)
    r = client.post(f"/api/rosters/{roster_id}/edit", json={"edits": [{"employee_id": "nobody", "date": "2026-12-02", "status": "work"}]}, headers=OPS)
    assert r.status_code == 400 and "not part of this roster" in r.json()["detail"]
    r = client.post(f"/api/rosters/{roster_id}/edit", json={"edits": [{"employee_id": "emp-karan", "date": "2026-12-02", "status": "dancing"}]}, headers=OPS)
    assert r.status_code == 400


def test_publish_locked_until_blockers_cleared_and_reviews_done(client):
    roster_id = generate(client)
    r = client.post(f"/api/rosters/{roster_id}/publish", headers=OPS)
    assert r.status_code == 400 and "pod lead review" in r.json()["detail"]
    pass_reviews(client, roster_id)
    assert detail(client, roster_id)["roster"]["status"] == "ops_review"
    r = client.post(f"/api/rosters/{roster_id}/publish", headers=OPS)
    assert r.status_code == 409 and "blocker" in r.json()["detail"]
    key = next(i["key"] for i in detail(client, roster_id)["issues"] if i["severity"] == "blocker")
    r = client.post(f"/api/rosters/{roster_id}/override", json={"key": key, "reason": "no"}, headers=OPS)
    assert r.status_code == 400 and "reason" in r.json()["detail"]
    override_all(client, roster_id)
    r = client.post(f"/api/rosters/{roster_id}/publish", headers=OPS)
    assert r.status_code == 200, r.text
    final = detail(client, roster_id)
    assert final["roster"]["status"] == "published"
    assert all(i["override_reason"] for i in final["issues"] if i["severity"] == "blocker")


def test_pod_lead_can_only_decide_for_their_own_pod(client):
    roster_id = generate(client)
    client.post(f"/api/rosters/{roster_id}/submit", headers=OPS)
    lead = {"X-Role": "pod_lead", "X-Pod-Id": "pod-aurora", "X-Actor-Name": "Meera"}
    assert client.post(f"/api/rosters/{roster_id}/pod-decision", json={"pod_id": "pod-delta", "approve": True}, headers=lead).status_code == 403
    r = client.post(f"/api/rosters/{roster_id}/pod-decision", json={"pod_id": "pod-aurora", "approve": False, "note": "Please swap Dev"}, headers=lead)
    assert r.json()["status"] == "draft"
    assert detail(client, roster_id)["roster"]["status"] == "draft"


def test_employee_role_cannot_change_rosters(client):
    roster_id = generate(client)
    who = {"X-Role": "employee", "X-Employee-Id": "emp-karan", "X-Actor-Name": "Karan"}
    assert client.post(f"/api/rosters/{roster_id}/edit", json={"edits": [{"employee_id": "emp-karan", "date": "2026-12-02", "status": "idle"}]}, headers=who).status_code == 403
    assert client.post("/api/rosters/generate", json={"month": "2026-12"}, headers=who).status_code == 403
    assert client.post("/api/setup/brands", json={"name": "Nope"}, headers=who).status_code == 403
    assert client.post("/api/leaves", json={"employee_id": "emp-karan", "leave_type": "planned", "start_date": "2026-12-09", "end_date": "2026-12-09"}, headers=who).status_code == 200


def test_editing_published_creates_a_new_version_and_notifies(client):
    first = generate(client)
    result = publish_flow(client, first)
    assert result["comp_offs_earned"] > 0
    d = detail(client, first)
    day = next(x for x in d["days"] if x["employee_id"] == "emp-sana" and x["status"] == "work")
    saved = client.post(f"/api/rosters/{first}/edit", json={"edits": [{"employee_id": "emp-sana", "date": day["date"], "status": "unavailable"}], "reason": "Family emergency"}, headers=OPS).json()
    second = saved["roster_id"]
    assert saved["new_version"] is True and second != first
    assert detail(client, first)["roster"]["status"] == "published"  # still live
    assert detail(client, second)["roster"]["version"] == 2
    assert detail(client, second)["roster"]["parent_id"] == first
    publish_flow(client, second)
    assert detail(client, first)["roster"]["status"] == "superseded"
    notes = client.get("/api/notifications").json()
    assert any(n["kind"] == "roster_changed" for n in notes)
    mine = client.get("/api/notifications?employee_id=emp-sana").json()
    assert any(n["kind"] == "schedule_changed" and "1 day" in n["title"] for n in mine)
    others = [n for n in client.get("/api/notifications?employee_id=emp-pooja").json() if n["kind"] == "schedule_changed"]
    assert others == []


def test_comp_offs_follow_the_latest_published_roster(client):
    roster_id = generate(client)
    publish_flow(client, roster_id)
    boot = client.get("/api/bootstrap").json()
    worked = {x["employee_id"] for x in detail(client, roster_id)["days"] if x["date"] == "2026-12-25" and x["status"] == "work"}
    assert worked
    ledger = [e for e in boot["comp_off_ledger"] if e["entry_date"] == "2026-12-25"]
    assert {e["employee_id"] for e in ledger} == worked
    assert all(e["reason"] == "Worked Christmas Day" for e in ledger)


def test_scenario_single_employee_brand(client):
    """The person holding all of a brand's processes is unavailable: flag, rank, fix."""
    roster_id = generate(client)
    d = detail(client, roster_id)
    day = next(x["date"] for x in d["days"] if x["employee_id"] == "emp-karan" and x["status"] == "work" and x["date"] >= "2026-12-09")
    impact = client.get(f"/api/impact/absence?employee_id=emp-karan&start={day}&end={day}&leave_type=unavailable").json()
    assert impact["brands_affected"] == ["Haldi House"]
    assert {g["brand_process_id"] for g in impact["gaps"]} == {"haldi-cs", "haldi-ret"}
    leave = client.post("/api/leaves", json={"employee_id": "emp-karan", "leave_type": "unavailable", "start_date": day, "end_date": day}, headers=OPS).json()
    decision = client.post(f"/api/leaves/{leave['id']}/decision", json={"status": "approved"}, headers=OPS).json()
    assert decision["regenerated"] is True
    new_id = decision["roster_id"]
    assert all(c["date"] >= day for c in decision["changes"])
    new = detail(client, new_id)
    assert new["roster"]["status"] == "draft" and new["roster"]["parent_id"] == roster_id
    rec = next(x for x in new["days"] if x["employee_id"] == "emp-karan" and x["date"] == day)
    assert rec["status"] == "unavailable"
    cs = next(c for c in new["coverage"] if c["brand_process_id"] == "haldi-cs" and c["date"] == day)
    assert cs["staffed"] >= cs["required"]  # a backup stepped in
    ret_gap = next(i for i in new["issues"] if i["brand_process_id"] == "haldi-ret" and i["date"] == day)
    advice = client.get(f"/api/rosters/{new_id}/recommend?brand_process_id=haldi-ret&date={day}").json()
    assert advice["options"], advice
    assert ret_gap["severity"] == "blocker"


def test_scenario_one_of_three_on_a_shared_process(client):
    roster_id = generate(client)
    d = detail(client, roster_id)
    working = {(x["employee_id"], x["date"]) for x in d["days"] if x["status"] == "work"}
    day = next(x for x in d["days_in_month"] if ("emp-riya", x) in working and ("emp-kabir", x) in working and x > "2026-12-06" and x.endswith(("7", "9", "0")))
    impact = client.get(f"/api/impact/absence?employee_id=emp-riya&start={day}&end={day}").json()
    assert "ember-cs" not in {g["brand_process_id"] for g in impact["gaps"]}
    assert any(c["process"] == "Ember Candles CS" for c in impact["coverage_still_met"])


def test_rejecting_leave_changes_nothing_and_cancelling_regenerates(client):
    roster_id = generate(client)
    r = client.post("/api/leaves/leave-priya/decision", json={"status": "rejected"}, headers=OPS).json()
    assert r["regenerated"] is False
    r = client.post("/api/leaves/leave-harsh/decision", json={"status": "rejected"}, headers=OPS).json()
    assert r["regenerated"] is True  # approved leave cancelled: Harsh is available again
    rec = next(x for x in detail(client, r["roster_id"])["days"] if x["employee_id"] == "emp-harsh" and x["date"] == "2026-12-14")
    assert rec["status"] == "work"
    assert roster_id


def test_rule_change_shows_up_on_an_existing_roster(client):
    roster_id = generate(client)
    before = detail(client, roster_id)["roster"]["metrics"]["blockers"]
    rule = client.post("/api/setup/coverage_rules", json={"brand_process_id": "lotus-cs", "rule_type": "date", "date": "2026-12-13", "min_staff": 1, "note": "Sale"}, headers=OPS)
    assert rule.status_code == 200, rule.text
    after = detail(client, roster_id)
    assert after["roster"]["metrics"]["blockers"] == before + 1
    assert any(i["brand_process_id"] == "lotus-cs" and i["date"] == "2026-12-13" for i in after["issues"])
    assert client.delete(f"/api/setup/coverage_rules/{rule.json()['id']}", headers=OPS).status_code == 200
    assert detail(client, roster_id)["roster"]["metrics"]["blockers"] == before


def test_new_pod_brand_process_and_person_work_without_code(client):
    pod = client.post("/api/setup/pods", json={"name": "Elm"}, headers=OPS).json()
    proc = client.post("/api/setup/processes", json={"code": "SOC", "name": "Social Media"}, headers=OPS).json()
    brand = client.post("/api/setup/brands", json={"name": "Fresh Fig", "pod_id": pod["id"]}, headers=OPS).json()
    bp = client.post("/api/setup/brand_processes", json={"brand_id": brand["id"], "process_id": proc["id"], "calendar_type": "custom", "weekday_mask": [0, 1, 2], "shift_id": "shift-general"}, headers=OPS).json()
    emp = client.post("/api/setup/employees", json={"name": "New Person", "pod_id": pod["id"]}, headers=OPS).json()
    client.post("/api/setup/allocations", json={"employee_id": emp["id"], "brand_process_id": bp["id"], "role": "primary", "workload_share": 100}, headers=OPS)
    d = detail(client, generate(client))
    worked = [a for a in d["assignments"] if a["brand_process_id"] == bp["id"]]
    assert worked and all(a["employee_id"] == emp["id"] for a in worked)
    assert len(d["days"]) == 35 * 31


def test_setup_errors_are_clear(client):
    r = client.post("/api/setup/brands", json={"name": "Nimbu Naturals"}, headers=OPS)
    assert r.status_code == 409 and "already exists" in r.json()["detail"]
    r = client.delete("/api/setup/processes/proc-cs", headers=OPS)
    assert r.status_code == 409 and "in use" in r.json()["detail"]
    r = client.post("/api/setup/coverage_rules", json={"brand_process_id": "lotus-cs", "rule_type": "weekday", "min_staff": 1}, headers=OPS)
    assert r.status_code == 422 and "weekday" in r.json()["detail"]
    r = client.post("/api/setup/employees", json={"name": "X", "weekly_off_policy": "fixed"}, headers=OPS)
    assert r.status_code == 422 and "fixed" in r.json()["detail"]
    r = client.post("/api/setup/employees", json={"name": "X", "max_consecutive_days": 99}, headers=OPS)
    assert r.status_code == 422
    assert client.post("/api/setup/nonsense", json={}, headers=OPS).status_code == 404
    assert client.patch("/api/setup/brands/missing", json={"name": "Y"}, headers=OPS).status_code == 404


def test_deactivated_employee_and_brand_leave_new_rosters(client):
    client.patch("/api/setup/employees/emp-pooja", json={"active": False}, headers=OPS)
    client.patch("/api/setup/brands/lotus", json={"active": False}, headers=OPS)
    d = detail(client, generate(client))
    assert not [x for x in d["days"] if x["employee_id"] == "emp-pooja"]
    assert not [c for c in d["coverage"] if c["brand_process_id"] == "lotus-cs"]
    assert any(i["brand_process_id"] == "tara-cs" and i["code"] == "NO_AVAILABLE_EMPLOYEE" for i in d["issues"])


def test_compare_creates_three_plans_with_equal_coverage(client):
    plans = client.post("/api/rosters/compare", json={"month": "2026-12"}, headers=OPS).json()
    assert [p["plan"] for p in plans] == ["coverage_first", "fairness_first", "preference_first"]
    assert len({p["metrics"]["gap_slots"] for p in plans}) == 1
    assert len(client.get("/api/rosters?month=2026-12").json()) == 3


def test_repair_endpoint_and_diff(client):
    roster_id = generate(client)
    r = client.post(f"/api/rosters/{roster_id}/repair", json={"change_from": "2026-12-15"}, headers=OPS).json()
    d = client.get(f"/api/rosters/{r['roster_id']}/diff/{roster_id}").json()
    assert all(c["date"] >= "2026-12-15" for c in d)
    assert len(d) == len(r["changes"])


def test_next_month_uses_published_history(client):
    from backend.db import database as db
    publish_flow(client, generate(client))
    with db.connect() as conn:
        inp = db.load_input(conn, 2027, 1)
    assert inp.history and max(h.date.isoformat() for h in inp.history) == "2026-12-31"
    d = detail(client, generate(client, month="2027-01"))
    hard = {"WEEKLY_OFF_MISSING", "MAX_CONSECUTIVE_EXCEEDED", "REST_TOO_SHORT"}
    assert not [i for i in d["issues"] if i["code"] in hard]


def test_exports(client):
    from openpyxl import load_workbook
    client.patch("/api/setup/employees/emp-karan", json={"name": "=HYPERLINK(1)"}, headers=OPS)
    roster_id = generate(client)
    r = client.get(f"/api/rosters/{roster_id}/export.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows and {x["Employee"] for x in rows} >= {"Priya Menon"}
    assert not any(x["Employee"].startswith("=") for x in rows)  # spreadsheet formula injection
    r = client.get(f"/api/rosters/{roster_id}/export.xlsx")
    book = load_workbook(io.BytesIO(r.content))
    assert book.sheetnames == ["Roster", "Coverage", "Issues"]
    assert book["Roster"].max_row >= 34 + 3
    assert book["Coverage"].max_row == 48
    assert not any(str(c.value).startswith("=") for row in book["Roster"].iter_rows() for c in row if c.value)


def test_explanation_template_without_a_key(client):
    roster_id = generate(client)
    key = next(i["key"] for i in detail(client, roster_id)["issues"] if i["severity"] == "blocker")
    r = client.post(f"/api/rosters/{roster_id}/explain", json={"key": key}).json()
    assert r["source"] == "template" and "What to do" in r["text"]


def test_gemini_success_is_stored_and_failure_falls_back(client, monkeypatch):
    from backend.services import ai
    roster_id = generate(client)
    issues = [i for i in detail(client, roster_id)["issues"] if i["severity"] == "blocker"]
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    calls = []

    def good(url, headers=None, json=None, timeout=None):
        calls.append(url)
        assert headers["x-goog-api-key"] == "test-key"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Plain words."}]}}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", good)
    first = client.post(f"/api/rosters/{roster_id}/explain", json={"key": issues[0]["key"]}).json()
    again = client.post(f"/api/rosters/{roster_id}/explain", json={"key": issues[0]["key"]}).json()
    assert first["source"] == "gemini" and first["text"] == "Plain words."
    assert again["cached"] is True and len(calls) == 1  # stored, so one call at most
    assert ai.DEFAULT_MODEL in calls[0]

    def limited(url, headers=None, json=None, timeout=None):
        return httpx.Response(429, json={}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", limited)
    fallback = client.post(f"/api/rosters/{roster_id}/explain", json={"key": issues[1]["key"]}).json()
    assert fallback["source"] == "template" and issues[1]["message"] in fallback["text"]

    def down(url, headers=None, json=None, timeout=None):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", down)
    assert client.post(f"/api/rosters/{roster_id}/explain", json={"key": issues[2]["key"]}).json()["source"] == "template"


def test_webhook_fires_on_publish_and_failure_does_not_block(client, monkeypatch):
    sent = []
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://example.test/hook")
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: sent.append(json) or httpx.Response(200, request=httpx.Request("POST", url)))
    publish_flow(client, generate(client))
    assert sent and sent[0]["event"] == "roster.published"

    def broken(url, json=None, timeout=None):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", broken)
    publish_flow(client, generate(client))


def test_keepalive_requires_the_secret_when_set(client, monkeypatch):
    assert client.get("/api/cron/keepalive").status_code == 200
    monkeypatch.setenv("CRON_SECRET", "abc")
    assert client.get("/api/cron/keepalive").status_code == 401
    assert client.get("/api/cron/keepalive", headers={"Authorization": "Bearer abc"}).status_code == 200


def test_reset_restores_sample_data(client):
    generate(client)
    client.post("/api/setup/brands", json={"name": "Temp"}, headers=OPS)
    boot = client.get("/api/bootstrap").json()
    assert len(boot["brands"]) == 26
    client.post("/api/demo/reset", headers=OPS)
    boot = client.get("/api/bootstrap").json()
    assert len(boot["brands"]) == 25 and client.get("/api/rosters?month=2026-12").json() == []


def test_vercel_entry_point_restores_the_original_path(client):
    import asyncio
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("vercel_entry", Path(__file__).parents[1] / "api" / "index.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen = {}

    async def fake_api(scope, receive, send):
        seen.update(scope)

    module.api = fake_api
    scope = {"type": "http", "path": "/api/index", "raw_path": b"/api/index", "query_string": b"path=rosters/abc/recommend&date=2026-12-01"}
    asyncio.run(module.app(scope, None, None))
    assert seen["path"] == "/api/rosters/abc/recommend"
    assert seen["query_string"] == b"date=2026-12-01"
    seen.clear()
    untouched = {"type": "http", "path": "/api/health", "query_string": b""}
    asyncio.run(module.app(untouched, None, None))
    assert seen["path"] == "/api/health"
