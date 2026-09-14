"""
Customer Memory across sessions.

What a customer says in one session is there in the next: `remember` writes a
fact during the conversation (and supersedes or retracts an earlier one), a
bounded set of active facts is rendered into the customer block at
SessionStart, and a mid-session fact is appended as a message rather than
re-rendered into the block, so the cached prefix never changes (ADR 0005).
When the customer ends the conversation, a Reflection sub-agent fills in what
the agent did not record and merges duplicates.
"""

import json

import pytest

from app import database
from app.harness.provider import Completion, ToolCall
from tests.conftest import chat as _chat
from tests.conftest import first_customer

pytestmark = pytest.mark.unit


def _calls(*specs):
    return Completion(
        content="", finish_reason="tool_calls",
        tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=json.dumps(a)) for i, (n, a) in enumerate(specs)),
    )


def _remember(kind="commitment", fact="Going live with Stripe in Q4", **extra):
    return _calls(("remember", {"kind": kind, "fact": fact, **extra}))


def _tool_messages(request):
    return [m for m in request.messages if m["role"] == "tool"]


def _rows(customer_id):
    return [dict(r) for r in database.get_connection().execute(
        "SELECT * FROM customer_memory WHERE customer_id = ? ORDER BY id", (customer_id,)
    ).fetchall()]


def _block(request):
    return request.messages[1]["content"]


def _end(client, session_id):
    return client.post("/sales-agent/end", json={"session_id": session_id})


# =========================================================================
# remember: a fact, a correction, a retraction
# =========================================================================
def test_remember_writes_a_memory_row(client, provider):
    cid = first_customer(client)["customer_id"]
    provider.script(_remember(), "Noted — Q4 it is.")
    r = _chat(client, "s1", "We're going live with Stripe in Q4.", cid)
    assert r.json()["reply"].startswith("Noted")

    (row,) = _rows(cid)
    assert row["kind"] == "commitment" and row["fact"] == "Going live with Stripe in Q4"
    assert row["status"] == "active" and row["source"] == "remember" and row["confidence"] == 0.9
    assert row["source_turn"] == r.json()["turn_id"] and row["created_at"] and row["updated_at"]
    result = json.loads(_tool_messages(provider.requests[1])[0]["content"])
    assert result["memory"]["id"] == row["id"] and result["memory"]["fact"] == row["fact"]


def test_the_next_session_starts_knowing_the_fact(client, provider):
    cid = first_customer(client)["customer_id"]
    provider.script(_remember(), "Noted.", "Welcome back.")
    _chat(client, "s1", "We're going live with Stripe in Q4.", cid)
    _chat(client, "s2", "Hi again.", cid)

    first, second = provider.requests[0], provider.requests[2]
    assert "Going live with Stripe in Q4" not in _block(first), "nothing was known when the first session started"
    assert "Going live with Stripe in Q4" in _block(second)
    assert "commitment" in _block(second)
    assert f"[m{_rows(cid)[0]['id']}]" in _block(second), "facts carry their id so the model can correct them"


def test_a_correction_supersedes_the_earlier_fact(client, provider):
    cid = first_customer(client)["customer_id"]
    provider.script(_remember(), "Noted.")
    _chat(client, "s1", "We're going live with Stripe in Q4.", cid)
    old_id = _rows(cid)[0]["id"]

    provider.script(_remember(fact="Going live with Stripe in Q1 next year", replaces=old_id), "Updated.", "Welcome back.")
    _chat(client, "s1", "Actually it slipped — Q1 next year.", cid)
    _chat(client, "s2", "Hi.", cid)

    old, new = _rows(cid)
    assert old["status"] == "superseded" and old["superseded_by"] == new["id"]
    assert new["status"] == "active" and new["fact"] == "Going live with Stripe in Q1 next year"
    block = _block(provider.requests[4])
    assert "Q1 next year" in block and "in Q4" not in block


def test_a_retracted_fact_is_no_longer_injected(client, provider):
    cid = first_customer(client)["customer_id"]
    provider.script(_remember(kind="need", fact="Needs Terminal for a pop-up shop"), "Noted.")
    _chat(client, "s1", "We need Terminal for a pop-up shop.", cid)
    mid = _rows(cid)[0]["id"]

    provider.script(_remember(kind="need", fact="", replaces=mid), "Dropped.", "Hi.")
    _chat(client, "s1", "Forget the pop-up shop, that's cancelled.", cid)
    _chat(client, "s2", "Hello.", cid)

    (row,) = _rows(cid)
    assert row["status"] == "retracted"
    assert "pop-up shop" not in _block(provider.requests[4])
    result = json.loads(_tool_messages(provider.requests[3])[-1]["content"])
    assert result["retracted"]["id"] == mid


def test_the_same_fact_is_never_remembered_twice(client, provider):
    cid = first_customer(client)["customer_id"]
    provider.script(_remember(), "Noted.", _remember(fact="going live with Stripe in Q4."), "Yes, I have that.")
    _chat(client, "s1", "We're going live with Stripe in Q4.", cid)
    _chat(client, "s1", "As I said, we go live in Q4.", cid)

    (row,) = _rows(cid)
    result = json.loads(_tool_messages(provider.requests[3])[-1]["content"])
    assert result["memory"]["id"] == row["id"] and "already" in result["note"].lower()

    provider.script(_reflection({"kind": "commitment", "fact": "Going live with Stripe in Q4", "confidence": 0.9},
                                {"kind": "preference", "fact": "Prefers email", "confidence": 0.8}), "done")
    r = _end(client, "s1")
    assert r.json()["remembered"] == 1, "reflection cannot duplicate what is already remembered"
    assert [m["fact"] for m in _rows(cid)] == ["Going live with Stripe in Q4", "Prefers email"]


def test_remember_validates_kind_and_replaces(client, provider):
    cid = first_customer(client)["customer_id"]
    provider.script(_remember(kind="rumour", fact="x"), "ok", _remember(replaces=999), "ok")
    _chat(client, "s1", "hi", cid)
    _chat(client, "s1", "hi", cid)
    assert _rows(cid) == []
    first = _tool_messages(provider.requests[1])[0]["content"]
    assert "need" in first and "objection" in first and "stage" in first, "the feedback lists the kinds"
    second = _tool_messages(provider.requests[3])[-1]["content"]
    assert "999" in second


def test_remember_is_denied_in_a_prospect_session(client, provider):
    provider.script(_remember(), "ok")
    _chat(client, "p1", "We're going live in Q4.")
    feedback = _tool_messages(provider.requests[1])[0]["content"]
    assert "customer_only" in feedback and "capture_lead" in feedback
    assert database.get_connection().execute("SELECT COUNT(*) FROM customer_memory").fetchone()[0] == 0


# =========================================================================
# The prefix stays append-only (ADR 0005)
# =========================================================================
# The prefix invariant with a mid-session remember lives with the other prefix assertions:
# tests/test_harness_chat.py::test_prefix_is_byte_identical_across_consecutive_turns.
def test_the_injected_set_is_bounded_and_most_recent_first(client, provider):
    cid = first_customer(client)["customer_id"]
    for i in range(15):
        database.add_memory(cid, kind="preference", fact=f"Preference number {i}", source_turn="t", source="remember", confidence=0.9)
    provider.script("Hi.")
    _chat(client, "s1", "Hello.", cid)

    block = _block(provider.requests[0]) + "\n"
    shown = sorted((i for i in range(15) if f"Preference number {i}\n" in block), key=lambda i: block.index(f"Preference number {i}\n"))
    assert shown == list(range(14, 2, -1))


# =========================================================================
# SessionEnd: reflection fills in what the agent did not record
# =========================================================================
def _reflection(*memories):
    return _calls(("save_memories", {"memories": list(memories)}))


def test_ending_the_conversation_runs_reflection_that_writes_merged_rows(client, provider):
    cid = first_customer(client)["customer_id"]
    provider.script(_remember(kind="need", fact="Wants to add Apple Pay"), "Noted.", "Sure — Checkout supports it out of the box.")
    _chat(client, "s1", "We want to add Apple Pay. Also, our CFO hates per-seat pricing, and we're comparing you with Adyen.", cid)
    _chat(client, "s1", "Does Checkout support it?", cid)
    recorded = _rows(cid)[0]["id"]

    provider.script(
        _reflection(
            {"kind": "objection", "fact": "CFO dislikes per-seat pricing", "confidence": 0.8},
            {"kind": "stage", "fact": "Comparing Stripe with Adyen", "confidence": 0.7},
            {"kind": "need", "fact": "Wants Apple Pay on Checkout", "confidence": 0.9, "replaces": recorded},
        ),
        "Three facts saved.",
    )
    r = _end(client, "s1")
    assert r.status_code == 200
    body = r.json()
    assert body["remembered"] == 3 and body["merged"] == 1

    reflection_request = provider.requests[-2]
    assert reflection_request.model == "deepseek-flash"
    task = reflection_request.messages[-1]["content"]
    assert "CFO hates per-seat pricing" in task and "Wants to add Apple Pay" in task, "reflection sees the conversation and what is already remembered"
    assert reflection_request.messages[0]["content"] != provider.requests[0].messages[0]["content"], "its own context, not the sales agent's"

    rows = _rows(cid)
    by_fact = {r["fact"]: r for r in rows}
    assert by_fact["Wants to add Apple Pay"]["status"] == "superseded"
    assert by_fact["Wants Apple Pay on Checkout"]["status"] == "active" and by_fact["Wants Apple Pay on Checkout"]["source"] == "reflection"
    assert by_fact["CFO dislikes per-seat pricing"]["kind"] == "objection" and by_fact["CFO dislikes per-seat pricing"]["confidence"] == 0.8
    assert database.load_session("s1")["ended_at"]

    provider.script("Welcome back.")
    _chat(client, "s2", "Hi.", cid)
    block = _block(provider.requests[-1])
    assert "CFO dislikes per-seat pricing" in block and "Wants Apple Pay on Checkout" in block and "Wants to add Apple Pay" not in block


def test_reflection_is_metered_as_a_session_end_pass(client, provider):
    cid = first_customer(client)["customer_id"]
    provider.script("Hi.", _reflection({"kind": "preference", "fact": "Prefers email", "confidence": 0.6}), "Saved.")
    _chat(client, "s1", "Email me rather than call, please.", cid)
    _end(client, "s1")

    row = database.get_connection().execute(
        "SELECT * FROM turn_metrics WHERE session_id = 's1' AND kind = 'session_end'"
    ).fetchone()
    assert row["subagent_calls"] == 1 and row["subagent_prompt_tokens"] > 0
    assert json.loads(row["hooks_json"])["reflected"] == 1
    summary = client.get("/api/metrics").json()["summary"]
    assert summary["turns"] == 1 and summary["reflections"] == 1


def test_a_session_ends_once_and_takes_no_more_turns(client, provider):
    cid = first_customer(client)["customer_id"]
    provider.script("Hi.", Completion(content="Nothing new to remember."))
    _chat(client, "s1", "Hello.", cid)
    assert _end(client, "s1").status_code == 200
    assert _end(client, "s1").status_code == 409
    assert _chat(client, "s1", "One more thing.", cid).status_code == 409
    assert _end(client, "never-seen").status_code == 404
    assert len(provider.requests) == 2, "reflection ran once; the refused turn never reached the model"


def test_ending_a_prospect_session_runs_no_reflection(client, provider):
    provider.script("Hi.")
    _chat(client, "p1", "Hello.")
    r = _end(client, "p1")
    assert r.status_code == 200 and r.json()["remembered"] == 0 and r.json()["reflected"] is False
    assert len(provider.requests) == 1


def test_a_failing_reflection_still_ends_the_session(client, provider):
    cid = first_customer(client)["customer_id"]
    provider.script("Hi.", RuntimeError("flash is down"))
    _chat(client, "s1", "Hello.", cid)
    r = _end(client, "s1")
    assert r.status_code == 200 and r.json()["reflected"] is False and r.json()["remembered"] == 0
    assert database.load_session("s1")["ended_at"]
    row = database.get_connection().execute("SELECT error FROM turn_metrics WHERE session_id = 's1' AND kind = 'session_end'").fetchone()
    assert "RuntimeError" in row["error"]
