"""
A customer gets a streamed answer through the harness.

Everything here drives the HTTP seam with a ScriptedProvider standing in for
DeepSeek. What the customer sees is asserted on the HTTP response; what the
model was sent is asserted on the requests the fake recorded.
"""

import json
import re

import pytest

from app import database, main
from app.harness.provider import Completion, Usage
from tests.conftest import chat as _chat
from tests.conftest import customers as _customers
from tests.conftest import first_customer as _customer
from tests.conftest import sse_events as _events

pytestmark = pytest.mark.unit


# =========================================================================
# The reply and the memory of it
# =========================================================================
def test_chat_returns_the_reply_and_remembers_both_sides(client, provider):
    provider.script("Hello! Happy to help with Stripe.")
    cid = _customer(client)["customer_id"]

    r = _chat(client, "s1", "hi", cid)

    assert r.status_code == 200
    assert r.json()["reply"] == "Hello! Happy to help with Stripe."
    memory = database.load_messages("s1")
    assert [m["role"] for m in memory] == ["user", "assistant"]
    assert memory[0]["content"] == "hi"


def test_request_is_built_in_the_fixed_order(client, provider):
    provider.script("ok")
    customer = _customer(client)

    _chat(client, "s1", "hi", customer["customer_id"])

    request = provider.requests[0]
    assert [m["role"] for m in request.messages] == ["system", "system", "user"], \
        "static prompt, customer block, then working memory"
    assert [t["function"]["name"] for t in request.tools][0] == "Skill", "tool definitions travel with every request"
    assert customer["customer_name"] in request.messages[1]["content"]
    assert customer["customer_name"] not in request.messages[0]["content"]


def test_prefix_is_byte_identical_across_consecutive_turns(client, provider):
    provider.script(
        Completion(content="first", reasoning_content="let me think"),
        "second",
    )
    cid = _customer(client)["customer_id"]

    _chat(client, "s1", "one", cid)
    _chat(client, "s1", "two", cid)

    first, second = provider.requests
    shared = len(first.messages)
    # Everything the model saw on turn one, plus its own reply, is an exact prefix of turn two.
    assert json.dumps(second.messages[:shared], sort_keys=True) == json.dumps(first.messages, sort_keys=True)
    assert second.messages[shared] == {"role": "assistant", "content": "first", "reasoning_content": "let me think"}
    assert second.messages[-1] == {"role": "user", "content": "two"}


def test_static_prompt_carries_policies_and_the_never_do_list_but_no_clock(client, provider):
    provider.script("ok")
    _chat(client, "s1", "hi")

    static = provider.requests[0].messages[0]["content"]
    policies = database.get_active_policies()
    assert policies and all(p["policy_title"] in static for p in policies)
    lowered = static.lower()
    for phrase in ("never claim to be human", "custom pricing", "tax", "roadmap", "security document", "fraud", "language"):
        assert phrase in lowered
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b|\d{2}:\d{2}:\d{2}", static), "no dates or times in the cached prefix"


# =========================================================================
# SessionStart binds the customer once
# =========================================================================
def test_customer_block_is_built_from_the_profile_at_session_start(client, provider):
    provider.script("ok")
    cid = _customer(client)["customer_id"]
    profile = database.get_customer(cid)
    usage = database.get_customer_product_usage(cid)

    _chat(client, "s1", "hi", cid)

    block = provider.requests[0].messages[1]["content"]
    assert profile["customer_name"] in block
    assert profile["business_model"] in block
    assert str(profile["annual_payment_volume"]) in block
    for row in usage:
        assert row["product_name"] in block


def test_session_without_a_customer_is_a_prospect(client, provider):
    provider.script("ok")
    _chat(client, "anon", "hi")

    assert "prospect" in provider.requests[0].messages[1]["content"].lower()
    assert database.load_session("anon")["customer_id"] is None


def test_unknown_customer_is_refused_not_downgraded(client, provider):
    r = _chat(client, "s1", "hi", "CUST-DOES-NOT-EXIST")
    assert r.status_code == 404
    assert database.load_session("s1") is None
    assert provider.requests == []


def test_session_cannot_switch_customer(client, provider):
    provider.script("ok")
    customers = _customers(client)
    _chat(client, "s1", "hi", customers[0]["customer_id"])

    r = _chat(client, "s1", "hi", customers[1]["customer_id"])
    assert r.status_code == 409
    assert len(provider.requests) == 1


# =========================================================================
# Streaming
# =========================================================================
def test_stream_emits_thinking_once_then_text_deltas_then_done(client, provider):
    provider.script(Completion(
        content="Stripe Checkout is a hosted payment page.",
        reasoning_content="The customer asks what Checkout is. Answer plainly.",
    ))
    cid = _customer(client)["customer_id"]

    with client.stream("POST", "/sales-agent/stream",
                       json={"session_id": "s1", "customer_id": cid, "message": "What is Checkout?"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _events(r.read().decode())

    names = [e for e, _ in events]
    assert names[0] == "thinking" and names.count("thinking") == 1
    assert names[-1] == "done"
    assert set(names[1:-1]) == {"text_delta"}
    assert "".join(d["text"] for e, d in events if e == "text_delta") == "Stripe Checkout is a hosted payment page."
    done = events[-1][1]
    assert done["reply"] == "Stripe Checkout is a hosted payment page."
    assert done["session_id"] == "s1"
    assert done["usage"]["prompt_tokens"] >= 0
    # Reasoning text never reaches the customer.
    assert all("Answer plainly" not in json.dumps(d) for _, d in events)


def test_stream_without_reasoning_has_no_thinking_event(client, provider):
    provider.script("plain")
    with client.stream("POST", "/sales-agent/stream", json={"session_id": "s1", "message": "hi"}) as r:
        names = [e for e, _ in _events(r.read().decode())]
    assert "thinking" not in names and names[-1] == "done"


# =========================================================================
# Failure stays friendly, session stays usable
# =========================================================================
def test_provider_failure_is_reported_gently_and_recorded(client, provider):
    provider.script(RuntimeError("upstream exploded"), "back again")
    cid = _customer(client)["customer_id"]

    r = _chat(client, "s1", "hi", cid)
    assert r.status_code == 200
    assert r.json()["error"] == "RuntimeError"
    assert "exploded" not in r.json()["reply"], "internal error text never reaches the customer"
    assert "try again" in r.json()["reply"].lower()

    metrics = client.get("/api/metrics?days=1").json()["summary"]
    assert metrics["turns"] == 1 and metrics["errors"] == 1

    r2 = _chat(client, "s1", "hi again", cid)
    assert r2.json()["reply"] == "back again"
    assert [m["role"] for m in database.load_messages("s1")] == ["user", "assistant"], \
        "a failed turn leaves no half-conversation behind"


def test_customer_disconnecting_mid_reply_still_gets_the_turn_metered(client, provider):
    provider.script("a long answer that the customer never waits for")
    harness = main.app.state.harness
    turn = harness.run_turn("s1", None, "hi")
    next(turn)  # first text delta is on its way…
    turn.close()  # …and the customer closes the tab

    summary = client.get("/api/metrics?days=1").json()["summary"]
    assert summary["turns"] == 1 and summary["errors"] == 1
    assert database.load_messages("s1") == [], "nothing half-written enters working memory"


# =========================================================================
# Metrics
# =========================================================================
def test_metrics_report_cache_hit_rate_latency_and_tokens(client, provider):
    provider.script(
        Completion(content="a", usage=Usage(prompt_tokens=100, completion_tokens=10, cache_hit_tokens=0, cache_miss_tokens=100)),
        Completion(content="b", usage=Usage(prompt_tokens=120, completion_tokens=10, cache_hit_tokens=96, cache_miss_tokens=24)),
    )
    cid = _customer(client)["customer_id"]
    _chat(client, "s1", "one", cid)
    _chat(client, "s1", "two", cid)

    summary = client.get("/api/metrics?days=1").json()["summary"]
    assert summary["turns"] == 2
    assert summary["cache_hit_rate"] == pytest.approx(96 / 220)
    assert summary["avg_prompt_tokens"] == pytest.approx(110)
    assert summary["avg_completion_tokens"] == pytest.approx(10)
    assert summary["avg_latency_ms"] >= 0
