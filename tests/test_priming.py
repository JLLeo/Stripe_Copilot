"""
Priming — the Decider names the Skills a turn calls for, and the harness puts
their bodies into the conversation before the model's first call.

What a customer, an operator or a developer could observe is what these tests
assert: the bytes sent to the main model (the primed `system` message, where it
sits, what it carries), the questions the Decider was asked and the state it was
given, the rows in working memory and turn metrics, and the streamed events.

Two lines bound the change and both are checked here: Priming only adds context —
nothing is taken from the model, so every Decider failure leaves the turn exactly
as it was — and a Skill body enters a Session at most once, whoever loads it.
"""

import json
import time

import pytest

from app import database
from app.harness.core import HarnessConfig
from app.harness.decider import Answers
from app.harness.provider import Completion, ToolCall, Usage
from app.harness.skills import load_skills
from app.metrics import summary
from tests.conftest import chat as _chat
from tests.conftest import first_customer
from tests.conftest import sse_events as _events

pytestmark = pytest.mark.unit

PRIMED = HarnessConfig(priming=True)
primed = pytest.mark.parametrize("harness_config", [PRIMED], indirect=True)
SKILLS = load_skills(PRIMED.skills_dir)
ALL = sorted(SKILLS)


def _calls(*specs):
    return Completion(
        content="", finish_reason="tool_calls",
        tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=json.dumps(a)) for i, (n, a) in enumerate(specs)),
    )


def _probabilities(**high: float) -> dict[str, float]:
    """Every skill low, the named ones as given — the shape of a real all-skills answer."""
    out = {name: 0.05 for name in ALL}
    out.update(high)
    return out


def _metrics(session_id: str) -> dict:
    row = database.get_connection().execute(
        "SELECT * FROM turn_metrics WHERE session_id = ? AND kind = 'turn' ORDER BY rowid DESC LIMIT 1", (session_id,)
    ).fetchone()
    return dict(row)


def _primed_message(request) -> dict | None:
    """The harness-authored system message just before the customer's message, if the turn was primed."""
    candidate = request.messages[-2] if len(request.messages) >= 2 else None
    if candidate and candidate["role"] == "system" and candidate["content"].startswith("[Skills primed by the harness"):
        return candidate
    return None


def _stream(client, session_id, message, customer_id=None):
    body = {"session_id": session_id, "message": message}
    if customer_id:
        body["customer_id"] = customer_id
    with client.stream("POST", "/sales-agent/stream", json=body) as r:
        return _events(r.read().decode())


def _small_customer() -> str:
    return database.get_connection().execute(
        "SELECT customer_id FROM customers WHERE annual_payment_volume < 1000000 ORDER BY customer_id LIMIT 1"
    ).fetchone()[0]


# =========================================================================
# A primed turn
# =========================================================================
@primed
def test_a_primed_turn_puts_the_chosen_skills_in_before_the_customer_message(client, provider, decider):
    decider.script(_probabilities(pricing_conversation=0.97, payments=0.86))
    provider.script(_calls(("get_pricing", {"product": "Checkout"})), "2.9% + 30c per successful card charge.")

    r = _chat(client, "s1", "What does Checkout cost per transaction?")
    assert r.status_code == 200

    first = provider.requests[0]
    message = _primed_message(first)
    assert message is not None, "the primed message sits immediately before the customer's message"
    assert first.messages[-1] == {"role": "user", "content": "What does Checkout cost per transaction?"}
    assert "pricing_conversation" in message["content"].splitlines()[0] and "payments" in message["content"].splitlines()[0]
    assert "do not call Skill for them" in message["content"]
    assert SKILLS["pricing_conversation"].body in message["content"] and SKILLS["payments"].body in message["content"]
    assert message["content"].index(SKILLS["pricing_conversation"].body) < message["content"].index(SKILLS["payments"].body), \
        "the more probable skill comes first"
    assert SKILLS["billing"].body not in message["content"]

    (state, questions), = decider.requests
    assert sorted(questions) == ALL, "with nothing loaded yet, the Decider is asked about every skill, in one request"
    assert state["customer_message"] == "What does Checkout cost per transaction?"

    rows = database.load_messages("s1")
    assert [m["role"] for m in rows[:2]] == ["system", "user"], "persisted, and before the customer's message"
    assert rows[0] == message

    m = _metrics("s1")
    assert json.loads(m["primed_skills_json"]) == ["pricing_conversation", "payments"]
    assert m["priming_skipped"] is None and m["decider_ms"] >= 0
    assert m["redundant_skill_calls"] == 0 and m["skill_paired_with_tool"] == 0


@primed
def test_priming_never_narrows_what_the_model_may_do(client, provider, decider):
    decider.script(_probabilities(payments=0.9))
    provider.script("ok")
    _chat(client, "s1", "Does Checkout support Apple Pay?")

    request = provider.requests[0]
    names = [t["function"]["name"] for t in request.tools]
    assert "Skill" in names and len(names) == 11, "every tool stays available"
    assert request.tool_choice is None, "tool_choice is never forced by Priming"


# =========================================================================
# The selection rule
# =========================================================================
@pytest.mark.parametrize("harness_config", [HarnessConfig(priming=True, priming_threshold=0.55, priming_margin=0.15)], indirect=True)
def test_the_selection_rule_takes_one_or_two_and_the_top_two_within_the_margin(client, provider, decider):
    cases = [
        ("none above the threshold", _probabilities(payments=0.40, billing=0.30), [], "below_threshold"),
        ("one above", _probabilities(payments=0.90), ["payments"], None),
        ("two above, most probable first", _probabilities(billing=0.80, payments=0.90), ["payments", "billing"], None),
        ("three above, the second far behind", _probabilities(fraud_protection=0.95, terminal=0.70, payments=0.60), ["fraud_protection"], None),
        ("three above, the second close: a turn asking for two things",
         _probabilities(fraud_protection=0.92, terminal=0.89, payments=0.60), ["fraud_protection", "terminal"], None),
        ("three above, all close: still the top two, never nothing",
         _probabilities(fraud_protection=0.70, terminal=0.65, payments=0.60), ["fraud_protection", "terminal"], None),
        ("three above, the second exactly the margin behind, which floating point makes 0.15000000000000002",
         _probabilities(fraud_protection=0.85, terminal=0.70, payments=0.60), ["fraud_protection", "terminal"], None),
    ]
    for i, (label, answer, expected, skipped) in enumerate(cases):
        decider.script(answer)
        provider.script("ok")
        _chat(client, f"s{i}", "a question")
        message = _primed_message(provider.requests[-1])
        got = [] if message is None else message["content"].splitlines()[0]
        if expected:
            assert message is not None, label
            for name in expected:
                assert SKILLS[name].body in message["content"], label
            for name in set(ALL) - set(expected):
                assert SKILLS[name].body not in message["content"], label
        else:
            assert message is None, (label, got)
        m = _metrics(f"s{i}")
        assert json.loads(m["primed_skills_json"]) == expected, label
        assert m["priming_skipped"] == skipped, label


@pytest.mark.parametrize("harness_config", [HarnessConfig(priming=True, priming_threshold=0.45, priming_margin=0.40)], indirect=True)
def test_the_threshold_and_margin_come_from_the_configuration(client, provider, decider):
    # At 0.55 / 0.15 the first would prime nothing and the second only fraud_protection.
    decider.script(_probabilities(payments=0.50), _probabilities(fraud_protection=0.95, terminal=0.70, payments=0.60))
    provider.script("ok", "ok")
    _chat(client, "s1", "q")
    _chat(client, "s2", "q")
    assert SKILLS["payments"].body in _primed_message(provider.requests[0])["content"], "0.50 clears a 0.45 threshold"
    second = _primed_message(provider.requests[1])["content"]
    assert SKILLS["terminal"].body in second, "0.25 behind the top is within a 0.40 margin"
    assert json.loads(_metrics("s2")["primed_skills_json"]) == ["fraud_protection", "terminal"]


# =========================================================================
# At most once per Session
# =========================================================================
@primed
def test_skills_already_in_context_are_neither_asked_about_nor_put_in_again(client, provider, decider):
    decider.script(_probabilities(payments=0.9), _probabilities(billing=0.9, payments=0.9))
    provider.script(_calls(("Skill", {"name": "tax"})), "first answer", "second answer")
    _chat(client, "s1", "Checkout and tax?")
    _chat(client, "s1", "And subscriptions?")

    _, asked_second = decider.requests[1]
    assert "payments" not in asked_second, "primed on turn one"
    assert "tax" not in asked_second, "loaded by the model itself on turn one"
    assert sorted(asked_second) == sorted(set(ALL) - {"payments", "tax"})

    message = _primed_message(provider.requests[-1])
    assert message is not None and SKILLS["billing"].body in message["content"]
    assert SKILLS["payments"].body not in message["content"], "an already-loaded skill is never put in twice"
    everything = json.dumps(provider.requests[-1].messages)
    assert everything.count(json.dumps(SKILLS["payments"].body)[1:41]) == 1, "one copy of the payments body in the request"


@primed
def test_when_every_skill_is_in_context_the_decider_is_not_asked(client, provider, decider):
    decider.script(_probabilities(**{name: 0.9 for name in ALL[:2]}))
    provider.script(_calls(*[("Skill", {"name": n}) for n in ALL[2:]]), "ok", "again")
    _chat(client, "s1", "everything at once")
    _chat(client, "s1", "and again")
    assert len(decider.requests) == 1, "nothing left to ask about on the second turn"
    assert _metrics("s1")["priming_skipped"] == "all_loaded"


@primed
def test_a_redundant_skill_call_is_answered_from_context_and_counted(client, provider, decider):
    decider.script(_probabilities(payments=0.9))
    provider.script(_calls(("Skill", {"name": "payments"}), ("get_pricing", {"product": "Checkout"})), "ok")
    _chat(client, "s1", "Checkout?")

    results = {m["tool_call_id"]: m["content"] for m in provider.requests[1].messages if m["role"] == "tool"}
    assert "already in context" in results["c0"].lower() and SKILLS["payments"].body[:200] not in results["c0"], \
        "the model asked for a body it already had and got a short note, not a second copy"
    m = _metrics("s1")
    assert m["redundant_skill_calls"] == 1
    assert json.loads(m["skills_json"]) == [], "nothing was loaded by that call"
    assert json.loads(m["hooks_json"]).get("replaced") == 1


def test_a_skill_body_enters_a_session_at_most_once_even_with_priming_off(client, provider, decider):
    provider.script(_calls(("Skill", {"name": "tax"})), "first", _calls(("Skill", {"name": "tax"})), "second")
    _chat(client, "s1", "tax?")
    _chat(client, "s1", "tax again?")

    second = [m for m in provider.requests[-1].messages if m["role"] == "tool"][-1]
    assert "already in context" in second["content"].lower()
    memory = json.dumps(database.load_messages("s1"))
    assert memory.count(json.dumps(SKILLS["tax"].body)[1:41]) == 1, "one copy of the body in working memory"
    assert _metrics("s1")["redundant_skill_calls"] == 1
    assert decider.requests == [], "deduplication is not Priming; the Decider was never asked"


# =========================================================================
# Failure is always today's behaviour
# =========================================================================
@primed
def test_every_decider_failure_runs_the_turn_as_before_and_records_why(client, provider, decider):
    failures = [Answers(skipped="timeout", elapsed_ms=700), Answers(skipped="rate_limited"), RuntimeError("fell over"),
                Answers(skipped="malformed")]
    decider.script(*failures)
    for i, expected in enumerate(["timeout", "rate_limited", "transport", "malformed"]):
        provider.script("ok")
        r = _chat(client, f"s{i}", "What does Checkout cost?")
        assert r.status_code == 200 and r.json()["reply"] == "ok"
        request = provider.requests[-1]
        assert _primed_message(request) is None
        assert [m["role"] for m in request.messages] == ["system", "system", "user"], "exactly the request of an unprimed turn"
        assert _metrics(f"s{i}")["priming_skipped"] == expected


@primed
def test_the_time_spent_asking_is_measured_and_counted_in_the_turn(client, provider, decider, monkeypatch):
    ask = decider.ask

    def slow(state, questions):
        time.sleep(0.05)
        return ask(state, questions)

    monkeypatch.setattr(decider, "ask", slow)
    decider.script(_probabilities(payments=0.9))
    provider.script("ok")
    events = _stream(client, "s1", "q")
    m = _metrics("s1")
    assert m["decider_ms"] >= 50 and events[0][1]["decider_ms"] == m["decider_ms"]
    assert m["latency_ms"] >= m["decider_ms"], "the customer waited for the Decider too"


@primed
def test_a_decider_that_raises_despite_its_contract_still_cannot_fail_a_turn(client, provider, decider, monkeypatch):
    def boom(state, questions):
        raise ValueError("a future adapter with a bug")

    monkeypatch.setattr(decider, "ask", boom)
    provider.script("ok")
    r = _chat(client, "s1", "q")
    assert r.status_code == 200 and r.json()["reply"] == "ok"
    assert _metrics("s1")["priming_skipped"] == "error"


def test_with_priming_off_the_decider_is_never_asked_and_nothing_is_announced(client, provider, decider):
    provider.script("ok")
    events = _stream(client, "s1", "What does Checkout cost?")
    assert decider.requests == []
    assert "primed" not in [e for e, _ in events]
    assert [m["role"] for m in provider.requests[0].messages] == ["system", "system", "user"]
    m = _metrics("s1")
    assert m["priming_skipped"] == "priming_off" and json.loads(m["primed_skills_json"]) == [] and m["decider_ms"] == 0


# =========================================================================
# The prefix, and what a primed body must never become
# =========================================================================
@primed
def test_the_prefix_stays_byte_identical_across_primed_turns(client, provider, decider):
    decider.script(_probabilities(payments=0.9), _probabilities(billing=0.9))
    provider.script(Completion(content="first", reasoning_content="think"), "second")
    cid = first_customer(client)["customer_id"]
    _chat(client, "s1", "one", cid)
    _chat(client, "s1", "two", cid)

    first, second = provider.requests
    shared = len(first.messages)
    assert json.dumps(second.messages[:shared], sort_keys=True) == json.dumps(first.messages, sort_keys=True)
    assert second.messages[shared] == {"role": "assistant", "content": "first", "reasoning_content": "think"}
    assert _primed_message(second) is not None and second.messages[-1] == {"role": "user", "content": "two"}


@primed
def test_a_primed_body_is_never_the_customer_s_evidence_for_a_handoff(client, provider, decider):
    decider.script(_probabilities(pricing_conversation=0.95))
    quoted = "multi-product bundles, and country-specific rates"
    assert quoted in SKILLS["pricing_conversation"].body, "the evidence is a sentence only the primed skill contains"
    provider.script(
        _calls(("request_handoff", {"team": "Deal Desk / Pricing", "reason": "Wants custom pricing.", "evidence": quoted})),
        "Let me ask a little more first.",
    )
    _chat(client, "s1", "Can I get better rates?", _small_customer())

    result = [m for m in provider.requests[1].messages if m["role"] == "tool"][0]["content"]
    assert "handoff_validity" in result and "does not match anything the customer said" in result, \
        "the skill's words are not the customer's words"
    assert database.pending_handoff("s1") is None


@primed
def test_reflection_reads_the_conversation_not_the_primed_skill(client, provider, decider):
    decider.script(_probabilities(payments=0.9))
    provider.script("Checkout costs 2.9% + 30c.", Completion(content="nothing new"))
    cid = first_customer(client)["customer_id"]
    _chat(client, "s1", "What does Checkout cost?", cid)
    client.post("/sales-agent/end", json={"session_id": "s1"})

    task = provider.requests[-1].messages[-1]["content"]
    assert "What does Checkout cost?" in task
    assert SKILLS["payments"].body[:200] not in task and "[Skills primed by the harness" not in task


@pytest.mark.parametrize("harness_config", [HarnessConfig(
    priming=True, context_budget_tokens=10_000, summary_max_tokens=200, recent_window_tokens=300,
)], indirect=True)
def test_compaction_folds_a_primed_body_without_calling_it_the_customer_s(client, provider, decider):
    decider.script(_probabilities(payments=0.9), Answers(skipped="timeout"), Answers(skipped="timeout"),
                   Answers(skipped="timeout"))
    cid = first_customer(client)["customer_id"]
    over = Usage(prompt_tokens=8000, completion_tokens=20, cache_miss_tokens=8000)
    provider.script(
        Completion(content="Reply 0: " + "noted. " * 60, usage=Usage(prompt_tokens=2000, completion_tokens=20)),
        Completion(content="Reply 1: " + "noted. " * 60, usage=Usage(prompt_tokens=2000, completion_tokens=20)),
        Completion(content="Reply 2: " + "noted. " * 60, usage=over),
        "Summary of the conversation.", "ok",
    )
    for i in range(4):
        _chat(client, "s1", f"Message {i}: " + "customer detail, " * 30, cid)

    summariser = next(r for r in provider.requests if r.model == PRIMED.sub_model)
    folded = summariser.messages[-1]["content"]
    assert "[Skills primed by the harness" not in folded and SKILLS["payments"].body[:200] not in folded
    assert database.latest_compaction("s1")["skills"] == ["payments"], "a primed skill is an active skill the summary names"


@pytest.mark.parametrize("harness_config", [HarnessConfig(
    priming=True, context_budget_tokens=10_000, summary_max_tokens=200, recent_window_tokens=300,
)], indirect=True)
def test_compaction_keeps_a_primed_message_with_its_turn(client, provider, decider):
    decider.script(_probabilities(), _probabilities(payments=0.9), _probabilities())
    cid = first_customer(client)["customer_id"]
    provider.script(
        Completion(content="Hello.", usage=Usage(prompt_tokens=2000, completion_tokens=5)),
        Completion(content="Sure.", usage=Usage(prompt_tokens=8000, completion_tokens=5)),  # over the high-water mark
        "Summary of the short exchange.", "ok",
    )
    _chat(client, "s1", "Hi.", cid)
    _chat(client, "s1", "And Apple Pay?", cid)  # primed: the payments body is far bigger than the recent window
    _chat(client, "s1", "Thanks.", cid)

    after = provider.requests[-1].messages
    assert "Summary of the short exchange." in after[2]["content"]
    assert after[3]["role"] == "system" and after[3]["content"].startswith("[Skills primed by the harness: payments."), \
        "the turn kept verbatim starts at its primed message, not at the customer's words without it"
    assert after[4] == {"role": "user", "content": "And Apple Pay?"} and after[5]["content"] == "Sure."
    _, asked = decider.requests[-1]
    assert "payments" not in asked, "the body is still in context, so it is not asked about again"


# =========================================================================
# What the Decider is told
# =========================================================================
@primed
def test_the_decider_state_is_bounded_and_carries_what_the_spec_names(client, provider, decider):
    cid = first_customer(client)["customer_id"]
    for i in range(5):
        database.add_memory(cid, kind="preference", fact=f"Preference {i}", source_turn="t", source="remember", confidence=0.9)
    decider.script(_probabilities(), _probabilities())
    provider.script("A first reply. " * 100, "ok")
    _chat(client, "s1", "hello", cid)
    _chat(client, "s1", "x" * 20_000, cid)

    first, second = (state for state, _ in decider.requests)
    profile = database.get_customer(cid)
    assert first["customer"]["business_model"] == profile["business_model"]
    assert first["customer"]["annual_payment_volume"] == profile["annual_payment_volume"]
    assert isinstance(first["customer"]["products_in_use"], list)
    assert first["remembered"] == [f"preference: Preference {i}" for i in (4, 3, 2)], "the most recent Customer Memory, bounded"
    assert first["previous_agent_reply"] == "" and first["skills_in_context"] == [] and first["new_prospect"] is False

    assert len(second["customer_message"]) <= 4000, "a long message is cut for the Decider; the model still gets it all"
    assert second["previous_agent_reply"].startswith("A first reply.") and len(second["previous_agent_reply"]) <= 500
    assert set(first) == set(second), "the same shape every turn"


@primed
def test_a_prospect_s_state_has_no_customer(client, provider, decider):
    decider.script(_probabilities(discovery=0.9))
    provider.script("ok")
    _chat(client, "p1", "We are thinking about Stripe.")
    (state, _), = decider.requests
    assert state["new_prospect"] is True, "the Decider is told outright, as the model's customer block tells it"
    assert state["customer"] is None and state["remembered"] == []


# =========================================================================
# Skill paired with another tool in the first response
# =========================================================================
def test_a_first_response_pairing_a_skill_with_an_informed_tool_is_counted(client, provider, decider):
    cases = [
        ([("Skill", {"name": "payments"}), ("search_knowledge", {"question": "Apple Pay", "products": [], "topics": []})], 1),
        ([("Skill", {"name": "pricing_conversation"}), ("get_pricing", {"product": "Checkout"})], 1),
        ([("Skill", {"name": "discovery"}), ("capture_lead", {"company": "Acme"})], 1),  # discovery says what to record
        ([("Skill", {"name": "connect"}), ("get_my_profile", {})], 0),  # no instructions could change that call
        ([("Skill", {"name": "billing"}), ("Skill", {"name": "tax"})], 0),
        ([("get_pricing", {"product": "Checkout"})], 0),
    ]
    for i, (specs, expected) in enumerate(cases):
        provider.script(_calls(*specs), "ok")
        _chat(client, f"s{i}", "q")
        m = _metrics(f"s{i}")
        assert m["skill_paired_with_tool"] == expected, specs
        assert json.loads(m["first_skills_json"]) == [a["name"] for n, a in specs if n == "Skill"], "what the first response loaded"
        assert json.loads(m["first_tools_json"]) == [n for n, _ in specs if n != "Skill"], "and what else it called"


# =========================================================================
# Events, metrics, and the Skill tool's own words
# =========================================================================
@primed
def test_a_primed_turn_is_announced_before_anything_else_the_model_does(client, provider, decider):
    decider.script(_probabilities(payments=0.9))
    provider.script(Completion(content="ok", reasoning_content="hmm"))
    events = _stream(client, "s1", "q")
    names = [e for e, _ in events]
    assert names[0] == "primed" and names.index("primed") < names.index("thinking")
    data = events[0][1]
    assert data["skills"] == ["payments"] and data["skipped"] is None and data["decider_ms"] >= 0


@primed
def test_a_turn_that_primed_nothing_says_why(client, provider, decider):
    decider.script(_probabilities())
    provider.script("ok")
    events = _stream(client, "s1", "q")
    assert events[0] == ("primed", {"skills": [], "skipped": "below_threshold", "decider_ms": events[0][1]["decider_ms"]})


@primed
def test_the_metrics_summary_reports_priming(client, provider, decider):
    decider.script(_probabilities(payments=0.9), Answers(skipped="timeout"), _probabilities(billing=0.9), _probabilities())
    provider.script(
        _calls(("Skill", {"name": "payments"})), "ok", "ok", "ok",
        _calls(("request_handoff", {"team": "Sales Representative", "reason": "Asked for a person.", "evidence": "talk to a person"})),
        "Done — they will be in touch.",
    )
    _chat(client, "s1", "one")
    _chat(client, "s2", "two")
    _chat(client, "s3", "three")
    _chat(client, "s4", "I would like to talk to a person.")
    with client.stream("POST", "/sales-agent/confirm-handoff", json={"session_id": "s4", "accept": True}) as r:
        r.read()

    s = summary()
    assert s["turns"] == 5, "four customer messages and one turn resumed by the customer's answer"
    assert s["primed_turns"] == 2
    assert s["priming_share"] == pytest.approx(2 / 4), "a resumed turn answers no customer message: Priming did not run"
    assert s["priming_skip_reasons"] == {"below_threshold": 1, "timeout": 1}
    assert s["redundant_skill_calls"] == 1
    assert s["skill_paired_turns"] == 0


def test_the_skill_tool_says_to_load_instructions_before_calling_other_tools(client, provider):
    provider.script("ok")
    _chat(client, "s1", "q")
    skill = next(t for t in provider.requests[0].tools if t["function"]["name"] == "Skill")["function"]
    assert "before" in skill["description"] and "other tools" in skill["description"]
    assert "re-read" not in skill["description"], "a second load now returns a note, not the body"
