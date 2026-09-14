"""
Prospect sessions and lead capture.

A session without a customer is a prospect session: nothing is known until
the prospect says it. The `discovery` skill tells the model how to learn it,
and `capture_lead` writes what was learned as the session's Lead — one row
per session, refined as the conversation goes on.
"""

import json
import sqlite3

import pytest

from app import database
from app.harness.guardrails import leaks
from app.harness.skills import load_skills
from app.harness.provider import Completion, ToolCall
from tests.conftest import chat as _chat
from tests.conftest import first_customer

pytestmark = pytest.mark.unit


def _calls(*specs):
    return Completion(
        content="", finish_reason="tool_calls",
        tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=json.dumps(a)) for i, (n, a) in enumerate(specs)),
    )


def _lead(**fields):
    return _calls(("capture_lead", fields))


def _tool_messages(request):
    return [m for m in request.messages if m["role"] == "tool"]


def _hooks(session_id):
    row = database.get_connection().execute(
        "SELECT hooks_json FROM turn_metrics WHERE session_id = ? ORDER BY rowid DESC LIMIT 1", (session_id,)
    ).fetchone()
    return json.loads(row[0])


def _leads():
    return [dict(r) for r in database.get_connection().execute("SELECT * FROM leads ORDER BY id").fetchall()]


# =========================================================================
# A session without a customer is a prospect session
# =========================================================================
def test_a_session_without_a_customer_knows_nothing_yet(client, provider):
    provider.script(_calls(("get_my_profile", {})), "Tell me about your business.")
    r = _chat(client, "p1", "Hi, we're thinking about using Stripe.")
    assert r.status_code == 200

    block = provider.requests[0].messages[1]["content"]
    assert "prospect" in block.lower() and "nothing is known" in block.lower()
    assert "discovery" in block and "capture_lead" in block, "the block points at how to learn and where to record it"

    profile = json.loads(_tool_messages(provider.requests[1])[0]["content"])
    assert profile["profile"] is None and profile["products_in_use"] == []
    assert "prospect" in profile["note"].lower()
    assert database.load_session("p1")["customer_id"] is None


def test_the_customers_endpoint_offers_a_new_prospect_option(client):
    rows = client.get("/api/customers").json()
    assert rows[0] == {"customer_id": None, "customer_name": "New prospect", "industry": None,
                       "annual_payment_volume": None, "prospect": True}
    with sqlite3.connect(database.seed_db_path()) as seed:
        expected = seed.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    customers = [c for c in rows if not c["prospect"]]
    assert len(customers) == expected > 0
    assert all(c["customer_id"] for c in customers)


# =========================================================================
# The discovery skill
# =========================================================================
def test_the_discovery_skill_teaches_behaviour_and_quotes_no_internal_text():
    from app.harness.core import HarnessConfig

    skills = load_skills(HarnessConfig().skills_dir)
    assert "discovery" in skills
    body = skills["discovery"].body
    assert leaks(body) == []
    for marker in ("BANT", "Mid-Market", "Strategic", "CRM", "deal cycle", "Solutions Engineer for", "$100K"):
        assert marker.lower() not in body.lower(), marker
    for behaviour in ("capture_lead", "ask_customer", "request_handoff", "business model", "volume", "timeline"):
        assert behaviour in body, behaviour


def test_every_skill_body_is_free_of_internal_markers():
    from app.harness.core import HarnessConfig

    for name, skill in load_skills(HarnessConfig().skills_dir).items():
        assert leaks(skill.body) == [], name


# =========================================================================
# capture_lead
# =========================================================================
def test_a_prospect_session_leads_to_a_lead_row(client, provider):
    provider.script(
        _lead(company="Brightloom Coffee", business_model="Online store plus three cafés", annual_volume_usd=1_200_000,
              timeline="Launching the new site in about two months", needs="Card payments online and in person, Apple Pay",
              qualification_notes="Owner is deciding; currently on a legacy processor with a 3-year contract ending soon",
              recommended_products=["Payments", "Checkout", "Terminal"]),
        "Great — here's what I'd suggest to start with.",
    )
    r = _chat(client, "p1", "We're Brightloom Coffee, an online store plus three cafés, about $1.2M a year, launching in two months.")
    assert r.status_code == 200 and r.json()["reply"].startswith("Great")

    (lead,) = _leads()
    assert lead["session_id"] == "p1"
    assert lead["company"] == "Brightloom Coffee"
    assert lead["business_model"] == "Online store plus three cafés"
    assert lead["annual_volume_usd"] == 1_200_000
    assert lead["timeline"].startswith("Launching")
    assert lead["needs"].startswith("Card payments")
    assert lead["qualification_notes"].startswith("Owner is deciding")
    assert json.loads(lead["recommended_products_json"]) == ["Payments", "Checkout", "Terminal"]
    assert lead["created_at"] and lead["updated_at"]

    result = json.loads(_tool_messages(provider.requests[1])[0]["content"])
    assert result["lead"]["company"] == "Brightloom Coffee" and result["lead"]["id"] == lead["id"]


def test_later_calls_refine_the_same_lead(client, provider):
    provider.script(_lead(company="Brightloom Coffee", needs="Online card payments"), "Noted.",
                    _lead(annual_volume_usd=1_200_000, timeline="Two months", recommended_products=["Payments", "Checkout"]), "Got it.")
    _chat(client, "p1", "We're Brightloom Coffee and need online card payments.")
    _chat(client, "p1", "About $1.2M a year; we launch in two months.")

    (lead,) = _leads()
    assert lead["company"] == "Brightloom Coffee" and lead["needs"] == "Online card payments", "earlier facts survive"
    assert lead["annual_volume_usd"] == 1_200_000 and lead["timeline"] == "Two months"
    assert json.loads(lead["recommended_products_json"]) == ["Payments", "Checkout"]
    merged = json.loads(_tool_messages(provider.requests[3])[-1]["content"])["lead"]
    assert merged["company"] == "Brightloom Coffee" and merged["timeline"] == "Two months", "the model sees the whole lead"


def test_a_bad_value_never_costs_the_good_ones_their_write(client, provider):
    provider.script(_lead(company="Acme Outdoor", annual_volume_usd="lots", recommended_products="Payments"), "ok")
    _chat(client, "p1", "We're Acme Outdoor.")
    (lead,) = _leads()
    assert lead["company"] == "Acme Outdoor" and lead["annual_volume_usd"] is None
    result = json.loads(_tool_messages(provider.requests[1])[0]["content"])
    assert result["lead"]["company"] == "Acme Outdoor"
    assert len(result["ignored"]) == 2 and "annual_volume_usd" in result["ignored"][0] and "recommended_products" in result["ignored"][1]
    assert "annual_volume_usd" in result["still_unknown"]


def test_a_lead_needs_something_to_capture(client, provider):
    provider.script(_lead(), "Let me ask a few questions first.")
    _chat(client, "p1", "hi")
    assert _leads() == []
    feedback = _tool_messages(provider.requests[1])[0]["content"]
    assert "nothing" in feedback.lower() or "at least" in feedback.lower()


def test_capture_lead_is_denied_for_a_signed_in_customer(client, provider):
    cid = first_customer(client)["customer_id"]
    provider.script(_lead(company="Someone", needs="Radar"), "Understood.")
    _chat(client, "s1", "We'd like fraud protection.", cid)

    assert _leads() == []
    feedback = _tool_messages(provider.requests[1])[0]["content"]
    assert "prospect_only" in feedback and "profile" in feedback.lower()
    assert _hooks("s1")["denied"] == 1


def test_a_prospect_who_states_enterprise_volume_is_routed_to_enterprise_sales(client, provider):
    provider.script(
        _lead(company="Northwind Marketplace", business_model="Marketplace", annual_volume_usd=50_000_000), "Noted.",
        _calls(("request_handoff", {"team": "Deal Desk / Pricing", "reason": "Wants custom pricing.",
                                    "evidence": "we process about $50M a year and want custom pricing"})),
        "Let me bring in the right team.",
    )
    _chat(client, "p1", "We're Northwind Marketplace, we process about $50M a year and want custom pricing.")
    _chat(client, "p1", "Can you get us custom pricing?")

    feedback = _tool_messages(provider.requests[3])[-1]["content"]
    assert "enterprise_volume" in feedback and "Enterprise Sales" in feedback
    assert "50,000,000" in feedback


# =========================================================================
# Leads for the people who follow up
# =========================================================================
def test_recent_leads_are_listed_newest_first(client, provider):
    provider.script(_lead(company="First Co", needs="Payments"), "ok", _lead(company="Second Co", needs="Billing"), "ok")
    _chat(client, "p1", "First Co here, we need payments.")
    _chat(client, "p2", "Second Co here, we need billing.")

    rows = client.get("/api/leads").json()
    assert [r["company"] for r in rows] == ["Second Co", "First Co"]
    assert rows[0]["session_id"] == "p2" and rows[0]["recommended_products"] == []
    assert client.get("/api/metrics").json()["summary"]["leads_captured"] == 2
