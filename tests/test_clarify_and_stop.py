"""
Clarifying questions and the Stop hook.

`ask_customer` ends the turn with a question and clickable options; the
customer's click is simply the next message. Before any final reply reaches
the customer, the Stop hook checks it for placeholders and internal
markers and sends the model back to rewrite — the customer never sees the
rejected draft.
"""

import json

import pytest

from app import database
from app.harness.guardrails import find_placeholders, leaks
from app.harness.provider import Completion, ToolCall
from app.paths import KNOWLEDGE_BASE_DIR
from tests.conftest import chat as _chat
from tests.conftest import sse_events as _events

pytestmark = pytest.mark.unit


def _calls(*specs):
    return Completion(
        content="", finish_reason="tool_calls",
        tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=json.dumps(a)) for i, (n, a) in enumerate(specs)),
    )


def _ask(question="Do you sell one-off products, subscriptions, or both?", options=("One-off", "Subscriptions", "Both")):
    return _calls(("ask_customer", {"question": question, "options": list(options)}))


def _stream(client, session_id, message, customer_id=None):
    body = {"session_id": session_id, "message": message}
    if customer_id:
        body["customer_id"] = customer_id
    with client.stream("POST", "/sales-agent/stream", json=body) as r:
        return _events(r.read().decode())


def _small_customer():
    return database.get_connection().execute(
        "SELECT customer_id FROM customers WHERE annual_payment_volume < 1000000 ORDER BY customer_id LIMIT 1"
    ).fetchone()[0]


def _hooks(session_id):
    row = database.get_connection().execute(
        "SELECT hooks_json FROM turn_metrics WHERE session_id = ? ORDER BY rowid DESC LIMIT 1", (session_id,)
    ).fetchone()
    return json.loads(row[0])


# =========================================================================
# ask_customer
# =========================================================================
def test_a_clarifying_question_ends_the_turn_with_options(client, provider):
    provider.script(_ask())
    events = _stream(client, "s1", "How much would Stripe cost us?")

    names = [e for e, _ in events]
    assert names == ["tool_call", "ask_customer", "done"]
    asked = events[1][1]
    assert asked["question"] == "Do you sell one-off products, subscriptions, or both?"
    assert asked["options"] == ["One-off", "Subscriptions", "Both"]
    done = events[2][1]
    assert done["reply"] == asked["question"], "the question is the reply, in the model's own words"
    assert done["ask_customer"]["options"] == asked["options"]
    assert len(provider.requests) == 1, "no further model call: the customer's answer is the next turn"

    memory = database.load_messages("s1")
    assert [m["role"] for m in memory] == ["user", "assistant", "tool"], "a complete, valid transcript"
    assert "next message" in memory[2]["content"].lower()


def test_the_chosen_option_arrives_as_the_next_customer_message(client, provider):
    provider.script(_ask(), "Subscriptions — then Billing is the place to start.")
    _stream(client, "s1", "How much would Stripe cost us?")
    r = _chat(client, "s1", "Subscriptions")
    assert r.json()["reply"].startswith("Subscriptions —")
    second = provider.requests[1]
    assert second.messages[-1] == {"role": "user", "content": "Subscriptions"}
    assert second.messages[-2]["role"] == "tool", "the question's tool result precedes the answer"


def test_a_question_needs_two_to_five_options(client, provider):
    provider.script(_ask(options=("Only one",)), "fine, I'll just ask.")
    r = _chat(client, "s1", "hi")
    assert r.json()["reply"] == "fine, I'll just ask."
    feedback = [m for m in provider.requests[1].messages if m["role"] == "tool"][0]["content"]
    assert "2" in feedback and "5" in feedback


def test_other_tools_in_the_same_round_are_not_run_once_a_question_is_asked(client, provider):
    provider.script(_calls(("ask_customer", {"question": "Which region?", "options": ["EU", "US"]}), ("get_pricing", {"product": "Radar"})))
    events = _stream(client, "s1", "pricing?")
    assert "tool_result" not in [e for e, _ in events]
    memory = database.load_messages("s1")
    assert [m["role"] for m in memory] == ["user", "assistant", "tool", "tool"]
    assert "Not run" in memory[3]["content"]


def test_asking_is_recorded_in_metrics(client, provider):
    provider.script(_ask())
    _stream(client, "s1", "cost?")
    assert _hooks("s1")["asked_customer"] == 1


def test_a_question_that_would_leak_or_leave_blanks_is_denied_with_feedback(client, provider):
    provider.script(
        _calls(("ask_customer", {"question": "Do you qualify for our 5-15% discount range, [Customer Name]?", "options": ["Yes", "No"]})),
        _ask(),
    )
    events = _stream(client, "s1", "Can we get a discount?")
    names = [e for e, _ in events]
    assert names[:2] == ["tool_call", "hook_blocked"], "the question never reached the customer"
    assert names[-2:] == ["ask_customer", "done"]
    feedback = [m for m in provider.requests[1].messages if m["role"] == "tool"][0]["content"]
    assert "clean_question" in feedback and "5-15%" in feedback and "[Customer Name]" in feedback
    assert _hooks("s1")["denied"] == 1


# =========================================================================
# Stop hook: anti_placeholder and internal_canary
# =========================================================================
def test_a_reply_with_a_placeholder_is_rewritten_before_the_customer_sees_it(client, provider):
    provider.script("Dear [Customer Name], Checkout costs 2.9% + $0.30. Best regards, [Your Name]",
                    "Checkout costs 2.9% + $0.30 per successful card charge.")
    events = _stream(client, "s1", "What does Checkout cost?")

    streamed = "".join(d["text"] for e, d in events if e == "text_delta")
    assert "[Customer Name]" not in streamed and "[Your Name]" not in streamed
    assert events[-1][1]["reply"] == "Checkout costs 2.9% + $0.30 per successful card charge."
    assert len(provider.requests) == 2
    retry = provider.requests[1].messages
    assert retry[-2]["role"] == "assistant" and "[Customer Name]" in retry[-2]["content"]
    assert retry[-1]["role"] == "user" and "anti_placeholder" in retry[-1]["content"] and "[Customer Name]" in retry[-1]["content"]
    assert [m["role"] for m in database.load_messages("s1")] == ["user", "assistant"], "the rejected draft never enters working memory"
    assert database.load_messages("s1")[1]["content"].startswith("Checkout costs")
    assert _hooks("s1")["stop_denied"] == 1


def test_a_reply_leaking_internal_material_is_rewritten(client, provider):
    provider.script("Our discount ranges are 5-15% off for $1M-$10M volume — INTERNAL ONLY.",
                    "Custom pricing is arranged by our pricing team; I can connect you with them.")
    events = _stream(client, "s1", "Can we get a discount?")
    streamed = "".join(d["text"] for e, d in events if e == "text_delta")
    assert "5-15%" not in streamed and "INTERNAL" not in streamed
    assert events[-1][1]["reply"].startswith("Custom pricing")
    assert "internal_canary" in provider.requests[1].messages[-1]["content"]
    assert _hooks("s1")["stop_denied"] == 1


def test_after_two_rewrites_a_safe_reply_replaces_the_draft(client, provider):
    provider.script("Hi [Customer Name]", "Hello [Client Name]", "Dear [Name]")
    events = _stream(client, "s1", "hi")
    reply = events[-1][1]["reply"]
    assert "[" not in reply and reply, "a fixed safe reply, never the placeholder"
    assert len(provider.requests) == 3
    assert _hooks("s1")["stop_denied"] == 3 and _hooks("s1")["stop_gave_up"] == 1
    assert database.load_messages("s1")[1]["content"] == reply


def test_text_alongside_a_handoff_proposal_is_checked_too(client, provider):
    provider.script(Completion(
        content="Dear [Customer Name], shall I bring in our pricing team?", finish_reason="tool_calls",
        tool_calls=(ToolCall(id="c0", name="request_handoff", arguments=json.dumps(
            {"team": "Deal Desk / Pricing", "reason": "Customer asks for a volume discount.", "evidence": "we need a volume discount"}
        )),),
    ))
    events = _stream(client, "s1", "we need a volume discount", customer_id=_small_customer())
    done = events[-1][1]
    assert done["pending_handoff"]["team"] == "Deal Desk / Pricing"
    assert "[Customer Name]" not in done["reply"] and "Shall I go ahead?" in done["reply"], "the harness's own proposal stands in"
    assert "[Customer Name]" not in "".join(d.get("text", "") for e, d in events if e == "text_delta")
    assert _hooks("s1")["stop_denied"] == 1


def test_sign_off_and_blank_placeholders_are_caught():
    assert find_placeholders("Sincerely, [Sales Rep]") == ["[Sales Rep]"]
    assert find_placeholders("Thanks, [Sales Representative]\nDear ______,") == ["[Sales Representative]", "______"]
    assert find_placeholders("[Account Executive] | Your fee: [X]% | <your company>") == ["[Account Executive]", "[X]", "<your company>"]
    assert find_placeholders("See [Stripe Link] and [Stripe Radar for Fraud Teams]; contact <sales@example.com>.") == []


def test_source_citations_and_markdown_links_are_not_placeholders(client, provider):
    provider.script("Checkout supports Apple Pay [Stripe Checkout]. See [pricing](https://stripe.com/pricing) for the {fee} — sorry, for the fee.")
    events = _stream(client, "s1", "Apple Pay?")
    assert len(provider.requests) == 1, "citations, links and single braces are not placeholders"
    assert events[-1][1]["reply"].startswith("Checkout supports")


# =========================================================================
# The zero-leak helper the evaluation suite will reuse
# =========================================================================
def test_leaks_names_every_internal_marker_it_finds():
    found = leaks("INTERNAL ONLY — our Discount Ranges give 15-25% off; escalate to the VP of Sales via the deal desk tool.")
    assert {"INTERNAL ONLY", "Discount Ranges", "15-25%", "VP of Sales", "deal desk tool"} <= set(found)
    assert leaks("Stripe Checkout costs 2.9% + $0.30 and supports Apple Pay.") == []
    assert leaks("Radar for Fraud Teams is $0.02 per transaction, and disputes cost $15.") == []


def test_leak_markers_are_derived_from_the_internal_documents_too():
    assert leaks("Let me walk you through the Enterprise Security Review Process.") != []
    assert leaks("Our BANT+ Qualification Framework says you're mid-market.") != []


def test_public_wording_is_never_a_leak_marker():
    # Public documents share their section structure and some phrases with the internal ones;
    # only what no public document says can be a canary, or honest answers would be rewritten.
    assert leaks("Key discovery questions: do you sell online or in person?") == []
    assert leaks("Platform buy-rates are discounted rates for Connect platforms.") == []
    assert leaks("We do not share SOC reports without an NDA.") == []
    for path in KNOWLEDGE_BASE_DIR.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        if "Access Level: public" in text:
            assert leaks(text) == [], path.name
