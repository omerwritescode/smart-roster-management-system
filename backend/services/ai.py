"""Plain-English explanations from the Gemini free tier, with a template fallback.

Gemini only rewords facts the validator has already established. It never decides
anything about the roster. Each explanation is stored, so the same issue costs one
call at most. Only the fictional sample data goes through it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

import httpx

from backend.engine.explain import template_explanation

log = logging.getLogger("roster.ai")
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
DAILY_CAP = 200  # stored calls per day; keeps a public demo inside free limits

PROMPT = """You explain staff rostering problems to an operations manager.
Rewrite the facts below in 2 to 4 plain sentences: what happened, why it matters to the brand, and the next step.
Rules: use only these facts. Do not invent names, numbers, dates or causes. Do not make the decision for the manager.
No headings, bullet points or preamble.

Facts (JSON):
{facts}"""


def facts_hash(issue: dict) -> str:
    payload = json.dumps(
        {"code": issue["code"], "message": issue["message"], "suggestion": issue.get("suggestion", ""), "facts": issue.get("facts", {})},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def call_gemini(issue: dict) -> tuple[str, str] | None:
    """Return (text, model), or None on any failure. Failures are normal on a free tier."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    facts = {k: issue.get(k) for k in ("code", "severity", "message", "suggestion", "facts")}
    body = {
        "contents": [{"parts": [{"text": PROMPT.format(facts=json.dumps(facts, default=str))}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 300},
    }
    try:
        response = httpx.post(API.format(model=model), headers={"x-goog-api-key": key}, json=body, timeout=12)
        if response.status_code != 200:
            log.warning("Gemini returned %s", response.status_code)
            return None
        parts = response.json()["candidates"][0]["content"]["parts"]
        text = " ".join(p.get("text", "") for p in parts).strip()
        return (text, model) if text else None
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        log.warning("Gemini call failed: %s", type(exc).__name__)
        return None


def explain(conn, issue: dict) -> dict:
    """Stored text if we have it, then Gemini, then the template."""
    digest = facts_hash(issue)
    stored = conn.execute(
        "select text, source, model from ai_explanations where facts_hash = %s", (digest,)
    ).fetchone()
    if stored and stored["source"] == "gemini":
        return {**stored, "cached": True}

    calls_today = conn.execute(
        "select count(*) as n from ai_explanations where source = 'gemini' and created_at > now() - interval '1 day'"
    ).fetchone()["n"]
    result = call_gemini(issue) if calls_today < DAILY_CAP else None
    if result:
        text, model = result
        source = "gemini"
    else:
        text, model, source = template_explanation(issue), None, "template"
    conn.execute(
        """insert into ai_explanations (facts_hash, text, source, model) values (%s, %s, %s, %s)
           on conflict (facts_hash) do update set text = excluded.text, source = excluded.source,
           model = excluded.model, created_at = now()""",
        (digest, text, source, model),
    )
    return {"text": text, "source": source, "model": model, "cached": False}
