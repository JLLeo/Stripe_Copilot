"""
Handoff — the agent proposes, the customer confirms, a human Team takes over.

The permission prompt of Claude Code, aimed at the customer: `request_handoff`
is a tool the model calls; guardrails validate it, the turn pauses for the
customer's confirmation, and only a confirmation records the handoff.
"""

import json

import pytest

from app import database
from app.harness.provider import Completion, ToolCall
from app.harness.skills import load_skills
from app.tools.handoff import TEAMS, team_for_policy
from tests.conftest import chat as _chat
from tests.conftest import sse_events as _events

pytestmark = pytest.mark.unit


def _calls(*specs):
    return Completion(
        content="", finish_reason="tool_calls",
        tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=json.dumps(a)) for i, (n, a) in enumerate(specs)),
    )


def _handoff(team="Deal Desk / Pricing", reason="Customer asks for a volume discount.", evidence="we need a volume discount"):
    return _calls(("request_handoff", {"team": team, "reason": reason, "evidence": evidence}))


def _tool_messages(request):
    return [m for m in request.messages if m["role"] == "tool"]


def _customers(client):
    return client.get("/api/customers").json()


def _big_customer(client):
    rows = database.get_connection().execute(
        "SELECT customer_id FROM customers WHERE annual_payment_volume > 10000000 ORDER BY customer_id LIMIT 1"
    ).fetchone()
    return rows[0]


def _small_customer(client):
    return database.get_connection().execute(
        "SELECT customer_id FROM customers WHERE annual_payment_volume < 1000000 ORDER BY customer_id LIMIT 1"
    ).fetchone()[0]


def _stream(client, session_id, message, customer_id=None):
    body = {"session_id": session_id, "message": message}
    if customer_id:
        body["customer_id"] = customer_id
    with client.stream("POST", "/sales-agent/stream", json=body) as r:
        return _events(r.read().decode())


def _confirm(client, session_id, accept):
    with client.stream("POST", "/sales-agent/confirm-handoff", json={"session_id": session_id, "accept": accept}) as r:
        return r.status_code, _events(r.read().decode()) if r.status_code == 200 else None


# =========================================================================
# Teams and the policy register
# =========================================================================
def test_seven_canonical_teams_and_every_policy_maps_onto_one():
    assert set(TEAMS) == {
        "Enterprise Sales", "Deal Desk / Pricing", "Solutions Engineering", "Security & Compliance",
        "Tax Specialist", "Risk / Fraud", "Sales Representative",
    }
    from app.tools.handoff import POLICY_TEAM_MAP

    for policy in database.get_active_policies():
        assert policy["handoff_team"] in POLICY_TEAM_MAP, policy["handoff_team"]
        assert team_for_policy(policy["handoff_team"]) in TEAMS
    assert team_for_policy("Sales Ops / Pricing Team") == "Deal Desk / Pricing"
    assert team_for_policy("Security / Legal") == "Security & Compliance"
    assert team_for_policy("Legal / Tax Specialist") == "Tax Specialist"
    assert team_for_policy("something new") == "Sales Representative", "unknown names fall back to a human rep"


def test_static_prompt_names_the_team_behind_each_policy(client, provider):
    provider.script("ok")
    _chat(client, "s1", "hi")
    static = provider.requests[0].messages[0]["content"]
    assert "hand off to Deal Desk / Pricing" in static
    assert "Sales Ops / Pricing Team" not in static, "the register's own team names never reach the prompt"
    tool = next(t for t in provider.requests[0].tools if t["function"]["name"] == "request_handoff")
    assert sorted(tool["function"]["parameters"]["properties"]["team"]["enum"]) == sorted(TEAMS)
    assert tool["function"]["parameters"]["required"] == ["team", "reason", "evidence"]


# =========================================================================
# Guardrails: deny with feedback
# =========================================================================
def test_unknown_team_is_denied_with_feedback(client, provider):
    provider.script(_handoff(team="Legal"), "Let me rephrase.")
    r = _chat(client, "s1", "we need a volume discount")
    assert r.status_code == 200
    feedback = _tool_messages(provider.requests[1])[0]["content"]
    assert "handoff_validity" in feedback and "Legal" in feedback and "Deal Desk / Pricing" in feedback
    assert database.get_connection().execute("SELECT COUNT(*) FROM handoffs").fetchone()[0] == 0


def test_evidence_must_be_traceable_to_the_conversation_or_profile(client, provider):
    provider.script(_handoff(evidence="the customer said they process $50M a year"), "ok")
    _chat(client, "s1", "Can you tell me about Checkout?")
    feedback = _tool_messages(provider.requests[1])[0]["content"]
    assert "handoff_validity" in feedback and "evidence" in feedback.lower()

    provider.script(_handoff(evidence=""), "ok")
    _chat(client, "s2", "we need a volume discount")
    assert "evidence" in _tool_messages(provider.requests[3])[0]["content"].lower()


def test_evidence_cannot_be_manufactured_from_profile_field_names(client, provider):
    cid = _small_customer(client)
    provider.script(_handoff(team="Deal Desk / Pricing", reason="Large volume.",
                             evidence="customer has large annual payment volume and enterprise business model"), "ok")
    _chat(client, "s1", "Can you tell me about Checkout?", cid)
    feedback = _tool_messages(provider.requests[1])[0]["content"]
    assert "handoff_validity" in feedback, "field names are not facts; nothing the customer said supports this"


def test_evidence_from_the_profile_counts(client, provider):
    cid = _big_customer(client)
    volume = database.get_customer(cid)["annual_payment_volume"]
    provider.script(_handoff(team="Enterprise Sales", reason="Enterprise-scale volume.", evidence=f"annual payment volume {volume}"))
    events = _stream(client, "s1", "Can we talk about pricing?", cid)
    assert "handoff_pending" in [e for e, _ in events], "profile facts are evidence; the turn paused for confirmation"
    assert len(provider.requests) == 1, "nothing was denied, so the model was not asked again"


def test_a_customer_above_ten_million_always_goes_to_enterprise_sales(client, provider):
    cid = _big_customer(client)
    provider.script(_handoff(team="Deal Desk / Pricing"), "understood")
    _chat(client, "s1", "we need a volume discount", cid)
    feedback = _tool_messages(provider.requests[1])[0]["content"]
    assert "enterprise_volume" in feedback and "Enterprise Sales" in feedback
    row = database.get_connection().execute("SELECT hooks_json FROM turn_metrics WHERE session_id='s1'").fetchone()
    assert json.loads(row[0])["denied"] == 1


def test_a_small_customer_may_be_handed_to_any_team(client, provider):
    cid = _small_customer(client)
    provider.script(_handoff(team="Deal Desk / Pricing"))
    events = _stream(client, "s1", "we need a volume discount", cid)
    assert "handoff_pending" in [e for e, _ in events]


# =========================================================================
# Pause -> confirm -> record -> follow-up
# =========================================================================
def test_when_the_model_asks_in_its_own_words_those_words_are_the_reply(client, provider):
    asked = Completion(
        content="Möchten Sie, dass ich unser Pricing-Team einbinde?", finish_reason="tool_calls",
        tool_calls=(ToolCall(id="c0", name="request_handoff", arguments=json.dumps(
            {"team": "Deal Desk / Pricing", "reason": "Rabatt", "evidence": "wir brauchen einen Mengenrabatt"})),),
    )
    provider.script(asked)
    events = _stream(client, "s1", "wir brauchen einen Mengenrabatt")
    assert events[-1][1]["reply"] == "Möchten Sie, dass ich unser Pricing-Team einbinde?"


def test_a_valid_handoff_pauses_the_turn_for_the_customer(client, provider):
    provider.script(_handoff())
    events = _stream(client, "s1", "we need a volume discount")

    names = [e for e, _ in events]
    assert names == ["tool_call", "handoff_pending", "done"]
    pending = events[1][1]
    assert pending["team"] == "Deal Desk / Pricing" and pending["reason"] == "Customer asks for a volume discount."
    done = events[2][1]
    assert done["pending_handoff"]["team"] == "Deal Desk / Pricing"
    assert "Deal Desk / Pricing" in done["reply"] and "?" in done["reply"], "the reply asks the customer to confirm"
    assert "handoff_id" in done["pending_handoff"]

    memory = database.load_messages("s1")
    assert [m["role"] for m in memory] == ["user", "assistant"], "the tool result waits for the customer's answer"
    row = database.get_connection().execute("SELECT status, team FROM handoffs").fetchone()
    assert tuple(row) == ("pending", "Deal Desk / Pricing")
    assert json.loads(database.get_connection().execute("SELECT hooks_json FROM turn_metrics").fetchone()[0])["paused"] == 1


def test_confirming_records_the_handoff_and_the_agent_explains_next_steps(client, provider):
    cid = _small_customer(client)
    provider.script(_handoff(), "Done — our pricing team will reach out within two business days.")
    _stream(client, "s1", "we need a volume discount", cid)

    status, events = _confirm(client, "s1", accept=True)
    assert status == 200
    names = [e for e, _ in events]
    assert names[-1] == "done" and "text_delta" in names
    assert events[-1][1]["reply"].startswith("Done")

    row = dict(database.get_connection().execute("SELECT * FROM handoffs").fetchone())
    assert row["status"] == "confirmed" and row["team"] == "Deal Desk / Pricing" and row["customer_id"] == cid
    assert row["reason"] and row["evidence"] and row["session_id"] == "s1" and row["resolved_at"]

    memory = database.load_messages("s1")
    assert [m["role"] for m in memory] == ["user", "assistant", "tool", "assistant"]
    tool_result = json.loads(memory[2]["content"])
    assert tool_result["status"] == "confirmed" and tool_result["team"] == "Deal Desk / Pricing"
    follow_up_request = provider.requests[1]
    assert follow_up_request.messages[-1]["role"] == "tool", "the model continues from the tool result, nothing else was injected"


def test_declining_resumes_the_conversation_without_a_record(client, provider):
    provider.script(_handoff(), "No problem — let's continue with public pricing then.")
    _stream(client, "s1", "we need a volume discount")

    status, events = _confirm(client, "s1", accept=False)
    assert status == 200 and events[-1][1]["reply"].startswith("No problem")
    row = database.get_connection().execute("SELECT status FROM handoffs").fetchone()
    assert row[0] == "declined"
    assert database.get_connection().execute("SELECT COUNT(*) FROM handoffs WHERE status='confirmed'").fetchone()[0] == 0
    tool_result = json.loads(_tool_messages(provider.requests[1])[0]["content"])
    assert tool_result["status"] == "declined"


def test_confirming_when_nothing_is_pending_is_refused(client, provider):
    provider.script("hello")
    _chat(client, "s1", "hi")
    status, _ = _confirm(client, "s1", accept=True)
    assert status == 404


def test_a_stale_confirmation_card_is_refused(client, provider):
    provider.script(_handoff())
    _stream(client, "s1", "we need a volume discount")
    pending_id = database.pending_handoff("s1")["id"]
    with client.stream("POST", "/sales-agent/confirm-handoff", json={"session_id": "s1", "accept": True, "handoff_id": pending_id + 99}) as r:
        assert r.status_code == 409
    assert database.pending_handoff("s1")["id"] == pending_id, "still pending; nothing was resolved"


def test_a_provider_failure_after_confirming_leaves_a_valid_transcript(client, provider):
    provider.script(_handoff(), RuntimeError("model down"), "back again")
    _stream(client, "s1", "we need a volume discount")

    status, events = _confirm(client, "s1", accept=True)
    assert status == 200 and events[-1][0] == "error"
    memory = database.load_messages("s1")
    assert [m["role"] for m in memory] == ["user", "assistant", "tool"], "the tool result was written before the model was asked"
    assert database.get_connection().execute("SELECT status FROM handoffs").fetchone()[0] == "confirmed"

    r = _chat(client, "s1", "hello again")
    assert r.json()["reply"] == "back again", "the session is usable and the transcript valid"


def test_a_proposal_the_customer_never_saw_is_abandoned_not_declined(client, provider):
    # The customer disconnected while the question was on its way: the pending row exists,
    # but the assistant's tool call never reached working memory.
    provider.script("hi there", "and now?")
    _chat(client, "s1", "hello")
    database.create_pending_handoff(session_id="s1", customer_id=None, tool_call_id="ghost", team="Deal Desk / Pricing",
                                    reason="r", evidence="e")
    r = _chat(client, "s1", "anything new?")

    assert r.status_code == 200
    assert database.get_connection().execute("SELECT status FROM handoffs").fetchone()[0] == "abandoned"
    assert [m["role"] for m in database.load_messages("s1")] == ["user", "assistant", "user", "assistant"], \
        "no orphan tool result was appended"


def test_a_dangling_tool_call_is_settled_before_the_next_turn(client, provider):
    provider.script("first", "second")
    _chat(client, "s1", "hello")
    database.append_messages("s1", [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "lost", "type": "function", "function": {"name": "get_pricing", "arguments": "{}"}}]}])
    r = _chat(client, "s1", "still there?")
    assert r.status_code == 200
    memory = database.load_messages("s1")
    assert memory[3]["role"] == "tool" and memory[3]["tool_call_id"] == "lost" and "Not run" in memory[3]["content"]
    assert [m["role"] for m in memory] == ["user", "assistant", "assistant", "tool", "user", "assistant"]


def test_a_new_message_while_a_handoff_is_pending_counts_as_declining(client, provider):
    provider.script(_handoff(), "Sure, here is what Checkout does.")
    _stream(client, "s1", "we need a volume discount")
    r = _chat(client, "s1", "Actually, tell me about Checkout instead.")

    assert r.status_code == 200
    assert database.get_connection().execute("SELECT status FROM handoffs").fetchone()[0] == "declined"
    memory = database.load_messages("s1")
    assert [m["role"] for m in memory] == ["user", "assistant", "tool", "user", "assistant"], \
        "the dangling tool call is resolved before the new message, so the transcript stays valid"


def test_other_tools_in_the_same_round_are_not_run_once_the_turn_pauses(client, provider):
    provider.script(_calls(
        ("request_handoff", {"team": "Deal Desk / Pricing", "reason": "discount", "evidence": "volume discount"}),
        ("get_pricing", {"product": "Radar"}),
    ))
    events = _stream(client, "s1", "we need a volume discount")
    names = [e for e, _ in events]
    assert "handoff_pending" in names and "tool_result" not in names
    memory = database.load_messages("s1")
    assert [m["role"] for m in memory] == ["user", "assistant", "tool"]
    assert "Not run" in memory[2]["content"], "the skipped call still gets a result so the transcript stays valid"


# =========================================================================
# The policy skills
# =========================================================================
def test_the_policy_skills_exist_and_quote_no_internal_text():
    from app.harness.core import HarnessConfig

    skills = load_skills(HarnessConfig().skills_dir)
    assert {"pricing_conversation", "security_compliance", "objection_handling"} <= set(skills)
    internal_markers = (
        "INTERNAL ONLY", "5-15%", "15-25%", "25%+", "0.15%", "0.30%", "VP of Sales", "CRO", "deal desk tool",
        "vs. Adyen", "vs. Braintree", "vs. Square", "BANT", "Mid-Market", "Strategic AE", "price matching",
        "Can Never Share", "post-mortem", "internal_mock", "mock_policy",
    )
    for name in ("pricing_conversation", "security_compliance", "objection_handling"):
        body = skills[name].body
        for marker in internal_markers:
            assert marker.lower() not in body.lower(), (name, marker)
        assert "request_handoff" in body, "each policy skill says when to propose a handoff"


def test_loading_the_policy_skills_keeps_the_prompt_free_of_internal_material(client, provider):
    provider.script(_calls(("Skill", {"name": "pricing_conversation"}), ("Skill", {"name": "security_compliance"}),
                           ("Skill", {"name": "objection_handling"})), "ok")
    _chat(client, "s1", "hi")
    everything = json.dumps(provider.requests[1].messages)
    for marker in ("INTERNAL ONLY", "Discount Ranges", "5-15%", "Can Never Share"):
        assert marker not in everything
