"""
Skills on demand and the model's first tools.

Driven through the HTTP seam with a ScriptedProvider whose script contains
tool-call completions. What the model was told (skill bodies, tool results,
hook feedback) is asserted on the requests the fake recorded.
"""

import json
import re

import pytest

from app import database
from app.harness.core import Harness, HarnessConfig
from app.harness.guardrails import _boundary
from app.harness.provider import Completion, ToolCall
from app.harness.skills import SkillLoadError, load_skills
from app.metrics import init_metrics, summary
from tests.conftest import chat as _chat
from tests.conftest import customers as _customers
from tests.conftest import first_customer as _customer
from tests.conftest import sse_events as _events

pytestmark = pytest.mark.unit

PRODUCT_SKILLS = {"payments", "billing", "connect", "tax", "fraud_protection", "terminal", "data"}
POLICY_SKILLS = {"discovery", "pricing_conversation", "security_compliance", "objection_handling"}


def calls(*specs: tuple[str, dict]) -> Completion:
    """A completion in which the model calls one or more tools."""
    return Completion(
        content="",
        tool_calls=tuple(
            ToolCall(id=f"call_{i}", name=name, arguments=json.dumps(args)) for i, (name, args) in enumerate(specs)
        ),
        finish_reason="tool_calls",
    )


def _tool_messages(request) -> list[dict]:
    return [m for m in request.messages if m["role"] == "tool"]


def _metrics_row(session_id: str) -> dict:
    row = database.get_connection().execute(
        "SELECT * FROM turn_metrics WHERE session_id = ? ORDER BY rowid DESC LIMIT 1", (session_id,)
    ).fetchone()
    return dict(row)


# =========================================================================
# Skills: index in the prompt, body on demand
# =========================================================================
def test_static_prompt_lists_skill_descriptions_but_never_bodies(client, provider):
    provider.script("ok")
    _chat(client, "s1", "hi")

    static = provider.requests[0].messages[0]["content"]
    skills = load_skills(HarnessConfig().skills_dir)
    assert set(skills) == PRODUCT_SKILLS | POLICY_SKILLS
    for skill in skills.values():
        assert skill.description in static
        # A distinctive line from the body must not be in the prompt.
        first_heading = next(line for line in skill.body.splitlines() if line.startswith("## "))
        assert first_heading not in static


def test_model_loads_a_skill_then_calls_a_tool_then_answers(client, provider):
    provider.script(
        calls(("Skill", {"name": "billing"})),
        calls(("get_pricing", {"product": "Billing"})),
        "Billing is 0.7% of volume on pay-as-you-go.",
    )
    cid = _customer(client)["customer_id"]

    r = _chat(client, "s1", "How much does Billing cost?", cid)

    assert r.json()["reply"] == "Billing is 0.7% of volume on pay-as-you-go."
    first, second, third = provider.requests
    body = load_skills(HarnessConfig().skills_dir)["billing"].body
    assert body not in json.dumps(first.messages)
    assert _tool_messages(second)[0]["content"] == body, "the skill body arrives as the Skill tool's result"
    pricing = json.loads(_tool_messages(third)[1]["content"])
    assert pricing["product"] == "Billing"
    assert any("0.7%" in line for line in pricing["pricing"])

    memory = database.load_messages("s1")
    assert [m["role"] for m in memory] == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert memory[1]["tool_calls"][0]["function"]["name"] == "Skill"
    assert memory[2]["tool_call_id"] == memory[1]["tool_calls"][0]["id"]


def test_several_skills_can_be_loaded_in_one_round(client, provider):
    provider.script(calls(("Skill", {"name": "connect"}), ("Skill", {"name": "tax"})), "ok")
    _chat(client, "s1", "EU marketplace: Connect and Tax?")

    tool_msgs = _tool_messages(provider.requests[1])
    skills = load_skills(HarnessConfig().skills_dir)
    assert [m["content"] for m in tool_msgs] == [skills["connect"].body, skills["tax"].body]


def test_unknown_skill_is_reported_to_the_model_not_the_customer(client, provider):
    provider.script(calls(("Skill", {"name": "yachts"})), "Let me answer directly.")
    r = _chat(client, "s1", "hi")
    assert r.json()["reply"] == "Let me answer directly."
    feedback = _tool_messages(provider.requests[1])[0]["content"]
    assert "yachts" in feedback and "payments" in feedback, "feedback names the valid skills"


def test_skills_carry_no_tool_allowlist_and_definitions_are_stable(client, provider):
    provider.script("a", "b")
    _chat(client, "s1", "one")
    _chat(client, "s1", "two")
    a, b = provider.requests
    assert json.dumps(a.tools, sort_keys=True) == json.dumps(b.tools, sort_keys=True)
    names = [t["function"]["name"] for t in a.tools]
    assert names == ["Skill", "get_my_profile", "list_products", "get_pricing", "search_knowledge", "research", "request_handoff", "ask_customer", "capture_lead", "remember"]
    skill_tool = a.tools[0]["function"]
    assert sorted(skill_tool["parameters"]["properties"]["name"]["enum"]) == sorted(PRODUCT_SKILLS | POLICY_SKILLS)
    assert "allowed" not in json.dumps(a.tools)


def test_skill_frontmatter_is_validated_at_startup(tmp_path, provider):
    bad = tmp_path / "skills" / "billing"
    bad.mkdir(parents=True)
    (bad / "SKILL.md").write_text("---\nname: billing\n---\nNo description here.\n", encoding="utf-8")
    with pytest.raises(SkillLoadError, match="description"):
        Harness.build(provider=provider, config=HarnessConfig(skills_dir=tmp_path / "skills"))

    mismatched = tmp_path / "skills2" / "billing"
    mismatched.mkdir(parents=True)
    (mismatched / "SKILL.md").write_text("---\nname: invoicing\ndescription: x\n---\nbody\n", encoding="utf-8")
    with pytest.raises(SkillLoadError, match="directory"):
        load_skills(tmp_path / "skills2")


# =========================================================================
# The first tools
# =========================================================================
def test_get_my_profile_returns_only_the_bound_customer(client, provider):
    provider.script(calls(("get_my_profile", {})), "ok")
    customers = _customers(client)
    cid = customers[0]["customer_id"]

    _chat(client, "s1", "what do you know about us?", cid)

    profile = json.loads(_tool_messages(provider.requests[1])[0]["content"])
    assert profile["profile"]["customer_id"] == cid
    assert profile["profile"]["customer_name"] == customers[0]["customer_name"]
    assert isinstance(profile["products_in_use"], list)
    assert customers[1]["customer_name"] not in json.dumps(profile)
    assert provider.requests[0].tools[1]["function"]["parameters"]["properties"] == {}, "no customer_id parameter exists"


def test_get_my_profile_for_a_prospect_says_nothing_is_on_file(client, provider):
    provider.script(calls(("get_my_profile", {})), "ok")
    _chat(client, "anon", "hi")
    profile = json.loads(_tool_messages(provider.requests[1])[0]["content"])
    assert profile["profile"] is None and "prospect" in profile["note"].lower()


def test_list_products_reads_the_catalogue_with_optional_group(client, provider):
    provider.script(calls(("list_products", {})), calls(("list_products", {"group": "Revenue"})), "ok")
    _chat(client, "s1", "what do you sell?")

    everything = json.loads(_tool_messages(provider.requests[1])[0]["content"])
    revenue = json.loads(_tool_messages(provider.requests[2])[1]["content"])
    assert len(everything["products"]) == 26
    assert {p["product_group"] for p in revenue["products"]} == {"Revenue"}
    assert {"product_name", "product_group", "short_description"} <= set(everything["products"][0])


def test_get_pricing_reads_public_price_sections_only(client, provider):
    provider.script(
        calls(("get_pricing", {"product": "Radar"})),
        calls(("get_pricing", {"product": "Payments"})),
        calls(("get_pricing", {"product": "Billing"})),
        "ok",
    )
    _chat(client, "s1", "prices?")

    radar = json.loads(_tool_messages(provider.requests[1])[0]["content"])
    assert any("Radar" in line and "$0.02" in line for line in radar["pricing"])
    assert any("$15" in line for line in radar["pricing"]), "the product document's own Price section is included"
    assert radar["sources"] and all("internal" not in s for s in radar["sources"])
    dumped = json.dumps(radar).lower()
    assert "escalat" not in dumped and "discovery" not in dumped

    payments = json.loads(_tool_messages(provider.requests[2])[1]["content"])
    assert any("2.9%" in line and "$0.30" in line for line in payments["pricing"]), "card rates, not a substring match"

    billing = json.loads(_tool_messages(provider.requests[3])[2]["content"])
    assert any("$620" in line for line in billing["pricing"]), "figures the skills cite are retrievable"


def test_get_pricing_never_guesses_when_nothing_is_public(client, provider):
    provider.script(calls(("get_pricing", {"product": "Nothing Like This"})), "ok")
    _chat(client, "s1", "hi")
    unknown = json.loads(_tool_messages(provider.requests[1])[0]["content"])
    assert unknown["pricing"] == []
    assert "no public list price" in unknown["note"].lower() and "do not quote" in unknown["note"].lower()


def test_internal_documents_are_never_parsed_for_prices(client, provider):
    from app.tools.catalog import _price_entries

    sources = " ".join(e.source for e in _price_entries()).lower()
    assert "custom_pricing_policy" not in sources and "playbook" not in sources and "mock_security" not in sources


def test_bad_tool_arguments_come_back_as_feedback(client, provider):
    provider.script(
        Completion(content="", finish_reason="tool_calls",
                   tool_calls=(ToolCall(id="c1", name="get_pricing", arguments="{not json"),)),
        calls(("get_pricing", {})),
        calls(("no_such_tool", {})),
        "fine",
    )
    _chat(client, "s1", "hi")
    assert "JSON" in _tool_messages(provider.requests[1])[0]["content"]
    assert "product" in _tool_messages(provider.requests[2])[1]["content"], "missing required argument named"
    assert "no_such_tool" in _tool_messages(provider.requests[3])[2]["content"]


# =========================================================================
# Guardrails
# =========================================================================
def test_ninth_tool_round_is_denied_with_feedback_and_the_turn_still_ends(client, provider):
    provider.script(*[calls(("list_products", {"group": f"g{i}"})) for i in range(9)], "done")
    _chat(client, "s1", "hi")

    assert len(provider.requests) == 10
    ninth_result = _tool_messages(provider.requests[9])[-1]["content"]
    assert "turn_budget" in ninth_result and "8" in ninth_result
    assert provider.requests[9].tool_choice == "none", "after the budget the model must answer in text"
    assert provider.requests[8].tool_choice is None
    row = _metrics_row("s1")
    assert row["tool_rounds"] == 9
    assert json.loads(row["hooks_json"])["denied"] == 1
    assert "turn_budget: turn_budget" not in ninth_result, "hook name is not repeated in the feedback"


def test_a_model_that_ignores_tool_choice_none_is_stopped(client, provider):
    provider.script(*[calls(("list_products", {"group": f"g{i}"})) for i in range(20)])
    r = _chat(client, "s1", "hi")

    assert r.status_code == 200
    assert len(provider.requests) == 10, "budget round, forced-text round, then stop"
    assert "pick up where I left off" in r.json()["reply"]
    assert json.loads(_metrics_row("s1")["hooks_json"])["hard_stop"] == 1
    assert [m["role"] for m in database.load_messages("s1")][-1] == "assistant"


@pytest.mark.parametrize("harness_config", [HarnessConfig(result_cap_chars=400)], indirect=True)
def test_oversized_results_are_capped_at_a_boundary_with_a_note(client, provider):
    provider.script(calls(("list_products", {})), "ok")
    _chat(client, "s1", "hi")

    content = _tool_messages(provider.requests[1])[0]["content"]
    assert len(content) < 500
    assert re.search(r"\[truncated: showing \d+ of \d+ characters\]", content)
    body = content[: content.index("[truncated")].rstrip()
    assert body.endswith((".", "}", "]", ",", '"'))
    assert json.loads(_metrics_row("s1")["hooks_json"])["modified"] == 1, "a rewrite by result_cap is a recorded outcome"


def test_truncation_boundary_is_the_latest_one_in_the_window():
    text = "a" * 218 + "}," + " prose. " * 25
    cut = _boundary(text, 400)
    assert 360 <= cut <= 400, "a sentence end near the cap beats a JSON boundary far before it"
    assert text[:cut].rstrip().endswith(".")


def test_identical_tool_call_is_served_from_the_session_cache(client, provider):
    provider.script(
        calls(("get_pricing", {"product": "Tax"})),
        calls(("get_pricing", {"product": "Tax"})),
        "first turn",
        calls(("get_pricing", {"product": "Tax"})),
        "second turn",
    )
    _chat(client, "s1", "tax price?")
    _chat(client, "s1", "again?")

    assert _metrics_row("s1")["cache_hits"] == 1  # second turn: one lookup, one hit
    first_turn = database.get_connection().execute(
        "SELECT cache_hits FROM turn_metrics WHERE session_id='s1' ORDER BY rowid LIMIT 1"
    ).fetchone()[0]
    assert first_turn == 1  # first turn: two identical calls, the second was a hit


def test_skill_loads_are_never_cached(client, provider):
    provider.script(calls(("Skill", {"name": "tax"})), calls(("Skill", {"name": "tax"})), "ok")
    _chat(client, "s1", "hi")
    assert _metrics_row("s1")["cache_hits"] == 0
    assert json.loads(_metrics_row("s1")["skills_json"]) == ["tax", "tax"]


# =========================================================================
# Prefix stability, metrics, streaming
# =========================================================================
def test_prefix_stays_byte_identical_with_tools_in_play(client, provider):
    provider.script(
        calls(("Skill", {"name": "payments"})), "answer one",
        calls(("get_pricing", {"product": "Checkout"})), "answer two",
    )
    cid = _customer(client)["customer_id"]
    _chat(client, "s1", "one", cid)
    _chat(client, "s1", "two", cid)

    reqs = provider.requests
    assert len(reqs) == 4
    for earlier, later in ((reqs[0], reqs[1]), (reqs[1], reqs[2]), (reqs[2], reqs[3])):
        n = len(earlier.messages)
        assert json.dumps(later.messages[:n], sort_keys=True) == json.dumps(earlier.messages, sort_keys=True)
        assert json.dumps(later.tools, sort_keys=True) == json.dumps(earlier.tools, sort_keys=True)


def test_metrics_table_from_an_older_runtime_database_is_upgraded_in_place(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_DB_PATH", str(tmp_path / "old.db"))
    database.close_connection()
    conn = database.get_connection()
    conn.execute(
        "CREATE TABLE turn_metrics (turn_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, customer_id TEXT, "
        "created_at TEXT NOT NULL, model TEXT, prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0, "
        "reasoning_tokens INTEGER DEFAULT 0, cache_hit_tokens INTEGER DEFAULT 0, cache_miss_tokens INTEGER DEFAULT 0, "
        "provider_calls INTEGER DEFAULT 0, latency_ms INTEGER DEFAULT 0, error TEXT)"
    )
    conn.execute("INSERT INTO turn_metrics (turn_id, session_id, created_at) VALUES ('t0', 's0', '2099-01-01T00:00:00+00:00')")
    conn.commit()

    database.init_db()  # startup order: tables first, then metrics
    init_metrics()

    columns = {row[1] for row in conn.execute("PRAGMA table_info(turn_metrics)")}
    assert {"tool_rounds", "tools_json", "skills_json", "hooks_json", "cache_hits"} <= columns
    assert summary(days=36500)["turns"] == 1, "old rows survive and the summary query works"
    database.close_connection()


def test_metrics_record_tools_skills_hooks_and_rounds(client, provider):
    provider.script(calls(("Skill", {"name": "tax"}), ("get_pricing", {"product": "Tax"})), "ok")
    _chat(client, "s1", "hi")
    row = _metrics_row("s1")
    assert json.loads(row["tools_json"]) == ["Skill", "get_pricing"]
    assert json.loads(row["skills_json"]) == ["tax"]
    assert json.loads(row["hooks_json"])["allowed"] == 2
    assert row["tool_rounds"] == 1 and row["provider_calls"] == 2


def test_stream_shows_tool_activity_as_it_happens(client, provider):
    provider.script(calls(("Skill", {"name": "terminal"}), ("get_pricing", {"product": "Terminal"})), "Readers start at $59.")
    with client.stream("POST", "/sales-agent/stream", json={"session_id": "s1", "message": "reader prices?"}) as r:
        events = _events(r.read().decode())
    names = [e for e, _ in events]
    assert names[:4] == ["tool_call", "skill_loaded", "tool_call", "tool_result"]
    assert names[-1] == "done"
    assert set(names[4:-1]) == {"text_delta"}
    skill = dict(events[1][1])
    assert skill["name"] == "terminal"
    result = dict(events[3][1])
    assert result["name"] == "get_pricing" and result["cached"] is False and result["chars"] > 0
    assert "preview" not in result, "tool output never reaches the customer's client"


def test_stream_reports_hook_blocks(client, provider):
    provider.script(*[calls(("list_products", {"group": f"g{i}"})) for i in range(9)], "done")
    with client.stream("POST", "/sales-agent/stream", json={"session_id": "s1", "message": "hi"}) as r:
        events = _events(r.read().decode())
    blocked = [d for e, d in events if e == "hook_blocked"]
    assert len(blocked) == 1 and blocked[0]["hook"] == "turn_budget" and blocked[0]["tool"] == "list_products"
    assert "feedback" not in blocked[0], "hook feedback is for the model, not the browser"
