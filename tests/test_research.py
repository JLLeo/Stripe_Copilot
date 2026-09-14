"""
The research Sub-agent: a bounded loop on the cheaper model, its own context,
one tool, a cited Brief back to the main conversation.

Everything runs through the HTTP seam with one ScriptedProvider serving both
the main model and the sub-agent, so the recorded requests show exactly what
each was told.
"""

import json

import pytest

from app import database
from app.harness.core import HarnessConfig
from app.harness.provider import Completion, ToolCall, Usage
from app.harness.scripted import ScriptedProvider
from tests.conftest import FIXTURE_EMBEDDING_DIM
from tests.conftest import chat as _chat
from tests.conftest import first_customer as _customer
from tests.conftest import sse_events as _events
from tests.fixture_kb import INTERNAL_MARKER

pytestmark = pytest.mark.unit

BRIEF = "Checkout shows local wallets and Radar screens every payment [Stripe Checkout] [Stripe Radar]."


@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider(embedding_dim=FIXTURE_EMBEDDING_DIM)


@pytest.fixture
def harness_config(index_uri):
    return HarnessConfig(milvus_uri=index_uri)


def _calls(*specs):
    return Completion(
        content="", finish_reason="tool_calls",
        tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=json.dumps(a)) for i, (n, a) in enumerate(specs)),
        usage=Usage(prompt_tokens=100, completion_tokens=10),
    )


def _research(question="How do Checkout and Radar work together for fraud?"):
    return _calls(("research", {"question": question}))


def _search(question, products):
    return _calls(("search_knowledge", {"question": question, "products": products, "topics": []}))


def _requests_by_model(provider, model):
    return [r for r in provider.requests if r.model == model]


# =========================================================================
# Isolation: what the sub-agent is and is not told
# =========================================================================
def test_sub_agent_runs_on_its_own_model_with_only_the_search_tool(client, provider):
    provider.script(
        _research(),                                    # main: delegate
        _search("Checkout wallets", ["checkout"]),      # sub-agent round 1
        _search("Radar screening", ["radar"]),          # sub-agent round 2
        BRIEF,                                          # sub-agent: the brief
        "Here is what I found: " + BRIEF,               # main: final answer
    )
    cid = _customer(client)["customer_id"]
    _chat(client, "s1", "Do Checkout and Radar work together?", cid)

    config = HarnessConfig()
    sub = _requests_by_model(provider, config.sub_model)
    main = _requests_by_model(provider, config.main_model)
    assert len(sub) == 3 and len(main) == 2
    for request in sub:
        assert [t["function"]["name"] for t in request.tools] == ["search_knowledge"]
        assert request.messages[0]["role"] == "system"
        assert request.messages[1] == {"role": "user", "content": "How do Checkout and Radar work together for fraud?"}


def test_sub_agent_requests_contain_none_of_the_main_conversation(client, provider):
    provider.script(_research(), _search("wallets", ["checkout"]), BRIEF, "done")
    cid = _customer(client)["customer_id"]
    _chat(client, "s1", "Do Checkout and Radar work together?", cid)

    main_first = provider.requests[0]
    static_prompt, customer_block = main_first.messages[0]["content"], main_first.messages[1]["content"]
    for request in _requests_by_model(provider, HarnessConfig().sub_model):
        text = json.dumps(request.messages)
        assert static_prompt not in text and customer_block not in text
        assert "Do Checkout and Radar work together?" not in text, "the customer's words are not forwarded verbatim"
        assert "Skill" not in json.dumps(request.tools)


def test_only_the_brief_enters_working_memory(client, provider):
    provider.script(_research(), _search("wallets", ["checkout"]), _search("screening", ["radar"]), BRIEF, "final")
    _chat(client, "s1", "hi")

    memory = database.load_messages("s1")
    assert [m["role"] for m in memory] == ["user", "assistant", "tool", "assistant"]
    brief = json.loads(memory[2]["content"])
    assert brief["brief"] == BRIEF
    assert brief["tool_calls"] == 2
    assert "search_knowledge" not in json.dumps([m for m in memory if m["role"] == "tool"])
    assert INTERNAL_MARKER not in json.dumps(memory)


# =========================================================================
# The round cap
# =========================================================================
def test_round_cap_forces_a_brief_after_three_rounds(client, provider):
    provider.script(
        _research(),
        *[_search(f"query {i}", ["radar"]) for i in range(3)],  # three allowed rounds
        BRIEF,                                                  # forced text round
        "final",
    )
    _chat(client, "s1", "hi")

    sub = _requests_by_model(provider, HarnessConfig().sub_model)
    assert len(sub) == 4
    assert [r.tool_choice for r in sub] == [None, None, None, "none"]
    result = json.loads([m for m in database.load_messages("s1") if m["role"] == "tool"][0]["content"])
    assert result["brief"] == BRIEF and result["tool_calls"] == 3 and result["stopped_by_cap"] is True


def test_a_sub_agent_that_ignores_the_forced_text_round_still_returns_something(client, provider):
    provider.script(_research(), *[_search(f"q{i}", ["radar"]) for i in range(4)], "final")
    _chat(client, "s1", "hi")

    assert len(_requests_by_model(provider, HarnessConfig().sub_model)) == 4, "no fifth request"
    result = json.loads([m for m in database.load_messages("s1") if m["role"] == "tool"][0]["content"])
    assert "could not" in result["brief"].lower() and result["gave_up"] is True


# =========================================================================
# Sources, events, metrics, steering
# =========================================================================
def test_sources_found_by_the_sub_agent_reach_the_reply(client, provider):
    provider.script(_research(), _search("fraud scoring", ["radar"]), BRIEF, "final")
    r = _chat(client, "s1", "hi")
    sources = r.json()["sources"]
    assert sources and sources[0]["title"] == "Stripe Radar"
    assert all(s["url"].startswith("https://") for s in sources)


def test_only_documents_the_brief_cites_count_as_its_sources(client, provider):
    # The sub-agent reads Checkout, Radar and Billing passages but cites only Radar.
    provider.script(_research(), _search("fraud payments subscriptions", []), "Radar scores every payment [Stripe Radar].", "final")
    r = _chat(client, "s1", "hi")
    assert r.json()["sources"] == [{"title": "Stripe Radar", "url": "https://stripe.com/radar"}]


def test_a_brief_with_no_citations_keeps_every_source_it_read(client, provider):
    provider.script(_research(), _search("fraud scoring", ["radar"]), "Radar scores payments.", "final")
    r = _chat(client, "s1", "hi")
    assert r.json()["sources"], "an uncited brief still lets the customer see what was consulted"


def test_stream_shows_the_sub_agent_working(client, provider):
    provider.script(_research(), _search("wallets", ["checkout"]), _search("screening", ["radar"]), BRIEF, "final")
    with client.stream("POST", "/sales-agent/stream", json={"session_id": "s1", "message": "hi"}) as r:
        events = _events(r.read().decode())
    names = [e for e, _ in events]
    assert names[:6] == ["tool_call", "subagent_started", "subagent_tool_call", "subagent_tool_call", "subagent_finished", "tool_result"]
    started = events[1][1]
    assert started["name"] == "research"
    finished = events[4][1]
    assert finished["name"] == "research" and finished["rounds"] == 2 and finished["tool_calls"] == 2
    assert all(d["tool"] == "search_knowledge" for e, d in events if e == "subagent_tool_call")


def test_metrics_record_sub_agent_calls_and_tokens(client, provider):
    provider.script(_research(), _search("wallets", ["checkout"]), BRIEF, "final")
    r = _chat(client, "s1", "hi")

    row = dict(database.get_connection().execute("SELECT * FROM turn_metrics WHERE session_id='s1'").fetchone())
    assert row["subagent_calls"] == 1
    assert row["subagent_prompt_tokens"] > 0 and row["subagent_completion_tokens"] > 0
    assert row["provider_calls"] == 2, "the main model was called twice; sub-agent calls are counted separately"
    # main: delegate (100) + final answer (200); sub-agent: search (100) + brief (200) — booked apart
    assert r.json()["usage"]["prompt_tokens"] == 300, "main usage excludes the sub-agent's tokens"
    assert row["subagent_prompt_tokens"] == 300
    summary = client.get("/api/metrics?days=1").json()["summary"]
    assert summary["subagent_calls"] == 1


def test_progress_reaches_the_customer_while_the_sub_agent_is_still_working(client, provider):
    from app import main

    provider.script(_research(), _search("wallets", ["checkout"]), BRIEF, "final")
    turn = main.app.state.harness.run_turn("s1", None, "hi")

    first = next(turn)
    assert first.name == "tool_call" and first.data["name"] == "research"
    assert len(provider.requests) == 1, "the tool_call event is out before the sub-agent has made a single request"
    second = next(turn)
    assert second.name == "subagent_started"
    assert len(provider.requests) <= 2, "the start event is not held back until the delegation is over"
    rest = list(turn)
    assert [e.name for e in rest][:2] == ["subagent_tool_call", "subagent_finished"]


def test_a_cached_brief_is_served_without_booking_a_new_delegation(client, provider):
    call = _research("same question")
    provider.script(call, _search("wallets", ["checkout"]), BRIEF, "first", call, "second")
    _chat(client, "s1", "one")
    _chat(client, "s1", "again")

    rows = database.get_connection().execute(
        "SELECT subagent_calls, subagent_prompt_tokens, cache_hits FROM turn_metrics WHERE session_id='s1' ORDER BY rowid"
    ).fetchall()
    assert [tuple(r) for r in rows] == [(1, 300, 0), (0, 0, 1)]
    assert len(_requests_by_model(provider, HarnessConfig().sub_model)) == 2, "no sub-agent request on the cached turn"


def test_tool_descriptions_steer_search_first_and_research_for_hard_questions(client, provider):
    provider.script("ok")
    _chat(client, "s1", "hi")
    tools = {t["function"]["name"]: t["function"]["description"] for t in provider.requests[0].tools}
    assert "research" in tools["search_knowledge"]
    assert "search_knowledge" in tools["research"] and "several products" in tools["research"].lower()
    assert list(tools) == ["Skill", "get_my_profile", "list_products", "get_pricing", "search_knowledge", "research", "request_handoff", "ask_customer", "capture_lead"]
