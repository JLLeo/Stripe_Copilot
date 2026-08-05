"""
Unit tests for escalation gating logic.

No LLM calls, no Milvus. Pure rule evaluation.
"""

import pytest

from app.escalation import check_escalation, EscalationResult
from app.skills import SKILL_REGISTRY


pytestmark = pytest.mark.unit


# =========================================================================
# Explicit human requests SHOULD escalate
# =========================================================================
@pytest.mark.parametrize("query", [
    "I need to talk to a human",
    "Can I speak to a human please",
    "connect me to a real person",
    "connect me with someone who handles compliance",
    "put me in touch with your sales team",
    "I want to speak to a real person",
    "get me in touch with an account manager",
    "I need someone who can help with this",
    "I want to speak to your manager",
    "I'd like to file a complaint",
])
def test_explicit_human_request_escalates(query):
    result = check_escalation("escalation_request", "", query)
    assert result.should_escalate, f"Should escalate: {query}"
    assert result.escalation_team == "Sales Ops / Human Agent"


# =========================================================================
# Information questions should NOT escalate
# =========================================================================
@pytest.mark.parametrize("scenario,query", [
    ("escalation_request", "Can you help me understand billing?"),
    ("escalation_request", "I need help with my account"),
    ("security_compliance", "Is Stripe secure?"),
    ("security_compliance", "Can we get the SOC 2 report?"),
    ("security_compliance", "What encryption standards do you use?"),
    ("security_compliance", "Tell me about your compliance certifications"),
    ("pricing_negotiation", "What is the standard pricing?"),
    ("pricing_negotiation", "How much does Stripe cost?"),
    ("marketplace", "What is Stripe Connect?"),
    ("marketplace", "Tell me about payouts"),
    ("fraud_prevention", "How does Radar detect fraud?"),
    ("fraud_prevention", "We have high dispute rates, what tools help?"),
    ("saas_billing", "Does Stripe support recurring billing?"),
    ("ecommerce", "How does Checkout work?"),
])
def test_info_questions_do_not_escalate(scenario, query):
    result = check_escalation(scenario, "", query)
    assert not result.should_escalate, (
        f"Should NOT escalate [{scenario}]: {query} "
        f"(escalated to {result.escalation_team})"
    )


# =========================================================================
# Explicit specialist requests SHOULD escalate
# =========================================================================
@pytest.mark.parametrize("scenario,query,expected_team", [
    ("pricing_negotiation", "We need custom pricing for our volume", "Deal Desk / Pricing Team"),
    ("pricing_negotiation", "Do you offer volume discount tiers?", "Deal Desk / Pricing Team"),
    ("pricing_negotiation", "We want IC+ pricing", "Deal Desk / Pricing Team"),
    ("marketplace", "We need custom onboarding for our sellers", "Connect Specialist"),
    ("marketplace", "Help with cross-border payout setup", "Connect Specialist"),
    ("tax_compliance", "We need help with tax return filing", "Tax Team"),
])
def test_specialist_requests_escalate(scenario, query, expected_team):
    result = check_escalation(scenario, "", query)
    assert result.should_escalate, f"Should escalate [{scenario}]: {query}"
    assert expected_team in result.escalation_team


# =========================================================================
# Scenarios with no triggers NEVER escalate
# =========================================================================
NO_ESCALATION_SCENARIOS = [
    sid for sid, skill in SKILL_REGISTRY.items()
    if not skill.escalation_triggers
]


@pytest.mark.parametrize("scenario", NO_ESCALATION_SCENARIOS)
def test_no_trigger_scenarios_never_escalate(scenario):
    """Scenarios without escalation_triggers must never auto-escalate."""
    aggressive_queries = [
        "I need to talk to a human right now",
        "escalate this immediately",
        "connect me to your manager",
    ]
    for query in aggressive_queries:
        result = check_escalation(scenario, "", query)
        assert not result.should_escalate, (
            f"Scenario '{scenario}' has no triggers but escalated on: {query}"
        )


# =========================================================================
# Volume-based escalation
# =========================================================================
def test_enterprise_volume_escalates_pricing_scenario():
    """C001 has $12.5M annual volume — should trigger Enterprise on pricing."""
    result = check_escalation("pricing_negotiation", "C001", "what are the rates?")
    assert result.should_escalate
    assert "Enterprise" in result.escalation_team


def test_enterprise_volume_does_not_escalate_non_pricing():
    """High volume should NOT force escalation on non-pricing scenarios."""
    result = check_escalation("fraud_prevention", "C001", "how does Radar work?")
    assert not result.should_escalate


def test_unknown_customer_id_does_not_crash():
    result = check_escalation("pricing_negotiation", "NONEXISTENT", "pricing?")
    assert isinstance(result, EscalationResult)


# =========================================================================
# Edge cases
# =========================================================================
def test_empty_query_does_not_escalate():
    result = check_escalation("escalation_request", "", "")
    assert not result.should_escalate


def test_unknown_scenario_falls_back_gracefully():
    result = check_escalation("nonexistent_scenario", "", "talk to a human")
    assert isinstance(result, EscalationResult)


def test_case_insensitive_matching():
    """Triggers should match regardless of case."""
    lower = check_escalation("escalation_request", "", "connect me with someone")
    upper = check_escalation("escalation_request", "", "CONNECT ME WITH SOMEONE")
    assert lower.should_escalate == upper.should_escalate
