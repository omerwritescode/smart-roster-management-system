"""A connection failure must name its real cause and never reveal the connection details."""
import psycopg
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.db import database as db

SECRET = "s3cretPass"
POOLER = f"postgresql://postgres.abc:{SECRET}@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
client = TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("url, expected", [
    ("", "not set"),
    (f"DATABASE_URL={POOLER}", "start with postgresql://"),
    (f'"{POOLER}"', "start with postgresql://"),
    ("postgresql://postgres.abc:[YOUR-PASSWORD]@aws-0.pooler.supabase.com:6543/postgres", "square brackets"),
    ("postgresql://postgres.abc:pa/ss@aws-0.pooler.supabase.com:6543/postgres", "symbol"),
    (f"postgresql://postgres.abc:{SECRET}@1105@aws-0.pooler.supabase.com:6543/postgres", "@ symbol"),
    (f"postgresql://postgres:{SECRET}@db.abcdefgh.supabase.co:5432/postgres", "direct connection"),
    ("postgresql://aws-0.pooler.supabase.com:6543/postgres", "missing its username"),
])
def test_paste_mistakes_are_named(monkeypatch, url, expected):
    monkeypatch.setenv("DATABASE_URL", url)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert expected in response.json()["detail"]
    assert SECRET not in response.text


def test_a_good_pooler_string_passes_the_shape_check():
    db.check_url_shape(POOLER)


@pytest.mark.parametrize("driver_text, expected", [
    ('connection to server at "x", port 6543 failed: FATAL:  password authentication failed for user "postgres.abc"', "rejected the password"),
    ("FATAL:  Tenant or user not found", "does not recognise"),
    ('could not translate host name "x" to address: Name or service not known', "could not be reached"),
    ("failed to resolve host 'x': [Errno 16] Device or resource busy", "could not be reached"),
    ("connection timeout expired", "did not respond"),
    ("FATAL:  Max client connections reached", "too many"),
    ("something unexpected", "Vercel's Logs"),
])
def test_driver_errors_become_plain_reasons(monkeypatch, driver_text, expected):
    monkeypatch.setenv("DATABASE_URL", POOLER)

    def refuse(*args, **kwargs):
        raise psycopg.OperationalError(driver_text)

    monkeypatch.setattr(psycopg, "connect", refuse)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert expected in response.json()["detail"]
    assert "x" not in response.json()["detail"].split()  # no host names passed through


def test_logs_never_contain_the_password():
    text = f"failed for {POOLER}"
    assert SECRET not in db.redact(text)
    assert "***" in db.redact(text)
