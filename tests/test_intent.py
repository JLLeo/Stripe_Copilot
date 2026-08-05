"""
Unit tests for intent classification.

Only tests paths that do NOT call the LLM:
  - keyword matching (high confidence)
  - ultra-short follow-up context inheritance
  - out-of-scope fast-track
"""

import pytest

from app.intent import (
    CONFIDENCE_THRESHOLD,
    OUT_OF_SCOPE_THRESHOLD,
    STRIPE_SIGNAL_KEYWORDS,
    _is_ambiguous,
    classify_intent,
)
from app.skills import SKILL_REGISTRY


pytestmark = pytest.mark.unit


# =========================================================================
# Ambiguity detection (pure function)
# =========================================================================
@pytest.mark.parametrize("query,expected", [
    ("yes", True),
    ("tell me more", True),
    ("what about it", True),
    ("how does that work", True),
    ("Stripe Connect marketplace seller onboarding payouts", False),
    ("We need recurring subscription billing for our SaaS platform", False),
])
def test_ambiguity_detection(query, expected):
    assert _is_ambiguous(query) == expected


# =========================================================================
# Out-of-scope fast-track (no LLM)
# =========================================================================
@pytest.mark.parametrize("query", [
    "What's the weather today?",
    "Tell me a joke",
    "Who won the game last night?",
    "What time is it?",
])
def test_unrelated_queries_are_out_of_scope(query):
    result = classify_intent(query)
    assert result.scenario_id == "out_of_scope"
    assert result.method == "keyword"  # fast-track, no LLM
    assert result.confidence < OUT_OF_SCOPE_THRESHOLD


def test_stripe_signal_keywords_defined():
    assert len(STRIPE_SIGNAL_KEYWORDS) > 20
    # Key product terms must be present
    for kw in ["payment", "checkout", "billing", "fraud", "connect", "radar",
               "terminal", "security", "compliance", "pricing"]:
        assert kw in STRIPE_SIGNAL_KEYWORDS, f"Missing signal keyword: {kw}"


# =========================================================================
# Ultra-short follow-up inherits context (no LLM)
# =========================================================================
@pytest.mark.parametrize("query,prev_scenario", [
    ("yes", "fraud_prevention"),
    ("no", "pricing_negotiation"),
    ("sure", "marketplace"),
    ("ok", "saas_billing"),
])
def test_ultra_short_followup_inherits_scenario(query, prev_scenario):
    result = classify_intent(query, context_hint={"previous_scenario": prev_scenario})
    assert result.scenario_id == prev_scenario
    assert result.method == "keyword+context"
    assert result.context_used


def test_ultra_short_without_context_is_out_of_scope():
    """Without previous scenario, 'yes' has no meaning."""
    result = classify_intent("yes")
    assert result.scenario_id == "out_of_scope"


@pytest.mark.integration
def test_longer_query_does_not_inherit_blindly():
    """Queries >2 words should go through normal classification. (calls LLM)"""
    result = classify_intent(
        "what about pricing",
        context_hint={"previous_scenario": "marketplace"},
    )
    # Should NOT blindly inherit marketplace — goes through LLM/keyword path
    assert result.method != "keyword+context" or result.scenario_id != "marketplace"


# =========================================================================
# High-confidence keyword classification (no LLM)
# =========================================================================
@pytest.mark.parametrize("query,expected_scenario", [
    ("marketplace seller onboarding payout", "marketplace"),
    ("saas subscription recurring billing", "saas_billing"),
    ("fraud chargeback dispute risk", "fraud_prevention"),
    ("tax vat gst sales tax calculation", "tax_compliance"),
])
def test_high_confidence_keyword_classification(query, expected_scenario):
    """Queries with 3+ keyword matches should classify without LLM."""
    result = classify_intent(query)
    assert result.scenario_id == expected_scenario
    assert result.method == "keyword"
    assert result.confidence >= CONFIDENCE_THRESHOLD


# =========================================================================
# Multi-intent tracking
# =========================================================================
def test_all_matched_populated():
    result = classify_intent("marketplace seller onboarding payout")
    assert result.all_matched is not None
    assert len(result.all_matched) >= 1
    assert result.scenario_id in result.all_matched


def test_multi_intent_query_tracks_all_scenarios():
    result = classify_intent(
        "recurring subscription billing and SOC 2 compliance and fraud prevention"
    )
    # Should match multiple scenarios
    assert len(result.all_matched) >= 2


# =========================================================================
# Result validity
# =========================================================================
@pytest.mark.integration
def test_intent_always_in_registry_or_out_of_scope():
    """Classification must return a valid scenario or out_of_scope. (may call LLM)"""
    queries = [
        "marketplace payouts",
        "what's the weather",
        "recurring billing",
        "asdfghjkl random gibberish",
    ]
    valid = set(SKILL_REGISTRY.keys()) | {"out_of_scope"}
    for q in queries:
        result = classify_intent(q)
        assert result.scenario_id in valid, f"Invalid scenario for '{q}': {result.scenario_id}"


@pytest.mark.integration
def test_confidence_bounded():
    """(may call LLM)"""
    for q in ["marketplace payouts", "hello", "fraud prevention tools"]:
        result = classify_intent(q)
        assert 0.0 <= result.confidence <= 1.0


def test_empty_query():
    result = classify_intent("")
    assert result.scenario_id in set(SKILL_REGISTRY.keys()) | {"out_of_scope"}


# =========================================================================
# Customer profile prevents out_of_scope
# =========================================================================
@pytest.mark.integration
def test_customer_profile_prevents_out_of_scope():
    """With a customer loaded, vague queries should not be blocked. (calls LLM)"""
    result = classify_intent(
        "what are they using",
        context_hint={"has_customer_profile": True},
    )
    assert result.scenario_id != "out_of_scope"
