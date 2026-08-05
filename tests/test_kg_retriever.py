"""
Unit tests for KG query expansion.

No LLM calls, no Milvus. Pure keyword matching + graph traversal.
"""

import pytest

from app.kg_builder import get_knowledge_graph
from app.kg_retriever import get_kg_retriever


pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def kg():
    return get_kg_retriever()


@pytest.fixture(scope="module")
def graph():
    return get_knowledge_graph()


# =========================================================================
# Graph integrity
# =========================================================================
def test_graph_loads(graph):
    summary = graph.summary()
    assert summary["total_nodes"] > 50
    assert summary["total_edges"] > 100


def test_all_products_have_product_line(graph):
    products = graph.get_nodes_by_type("product")
    assert len(products) >= 15
    for p in products:
        assert "product_line" in p, f"Product {p['id']} missing product_line"


def test_scenario_patterns_exist(graph):
    patterns = graph.get_scenario_patterns()
    assert len(patterns) >= 12
    for sid, kws in patterns.items():
        assert len(kws) > 0, f"Scenario {sid} has no question_patterns"


# =========================================================================
# Scenario keyword matching
# =========================================================================
@pytest.mark.parametrize("query,expected_scenario", [
    ("we run a marketplace platform", "marketplace"),
    ("seller onboarding and payouts", "marketplace"),
    ("recurring subscription billing for saas", "saas_billing"),
    ("how do I prevent fraud", "fraud_prevention"),
    ("what about chargebacks", "fraud_prevention"),
    ("we need VAT handling for europe", "tax_compliance"),
    ("SOC 2 compliance requirements", "security_compliance"),
    ("penetration test policy", "security_compliance"),
    ("custom pricing discount", "pricing_negotiation"),
    ("in person payments with card reader", "in_person"),
    ("sell online without coding", "no_code"),
])
def test_scenario_keyword_matching(kg, query, expected_scenario):
    exp = kg.expand(query)
    assert expected_scenario in exp.matched_scenarios, (
        f"'{query}' should match {expected_scenario}, got {exp.matched_scenarios}"
    )


# =========================================================================
# Product alias matching
# =========================================================================
@pytest.mark.parametrize("query,expected_product", [
    ("tell me about Stripe Radar", "radar"),
    ("how does fraud detection work", "radar"),
    ("Stripe Connect for platforms", "connect"),
    ("Stripe Billing subscriptions", "billing"),
    ("Stripe Checkout page", "checkout"),
    ("Stripe Terminal card reader", "terminal"),
    ("Stripe Tax for VAT", "tax"),
    ("payment links no code", "payment_links"),
    ("Stripe Sigma reporting", "sigma"),
])
def test_product_alias_matching(kg, query, expected_product):
    exp = kg.expand(query)
    assert expected_product in exp.matched_products, (
        f"'{query}' should match product {expected_product}, got {exp.matched_products}"
    )


# =========================================================================
# Geography matching
# =========================================================================
@pytest.mark.parametrize("query,expected_geo", [
    ("customers in europe", "eu"),
    ("european payment methods", "eu"),
    ("US-based customers", "us"),
    ("expanding to asia", "apac"),
    ("selling in brazil", "latam"),
    ("international expansion", "global"),
])
def test_geo_matching(kg, query, expected_geo):
    exp = kg.expand(query)
    assert expected_geo in exp.matched_geos, (
        f"'{query}' should match geo {expected_geo}, got {exp.matched_geos}"
    )


# =========================================================================
# Graph traversal (1-hop expansion)
# =========================================================================
def test_radar_expands_to_related_products(kg):
    exp = kg.expand("Stripe Radar fraud detection")
    assert "radar" in exp.matched_products
    # Radar integrates with checkout and connect
    assert len(exp.related_products) > 0
    assert "radar" not in exp.related_products  # no self-reference


def test_billing_expands_to_tax_and_invoicing(kg):
    exp = kg.expand("Stripe Billing subscriptions")
    all_products = exp.all_products
    assert "billing" in all_products
    # Billing integrates with tax, invoicing, checkout
    assert len(all_products) > 1


def test_scenario_expands_to_products(kg):
    """Marketplace scenario should surface Connect even without explicit mention."""
    exp = kg.expand("we run a marketplace platform")
    assert "marketplace" in exp.matched_scenarios
    assert "connect" in exp.all_products


# =========================================================================
# Filter expression building
# =========================================================================
def test_filter_expr_format(kg):
    exp = kg.expand("Stripe Radar fraud")
    filter_expr = kg.build_filter_expr(exp)
    assert filter_expr is not None
    assert filter_expr.startswith("product in [")
    assert '"radar"' in filter_expr


def test_filter_expr_none_when_no_products(kg):
    exp = kg.expand("hello world nothing relevant")
    filter_expr = kg.build_filter_expr(exp)
    assert filter_expr is None


def test_all_products_deduplicates(kg):
    exp = kg.expand("Stripe Radar fraud prevention detection")
    all_p = exp.all_products
    assert len(all_p) == len(set(all_p)), "all_products contains duplicates"


# =========================================================================
# Confidence scoring
# =========================================================================
def test_confidence_increases_with_matches(kg):
    vague = kg.expand("hello")
    specific = kg.expand("Stripe Radar fraud prevention for European marketplace")
    assert specific.confidence > vague.confidence


def test_confidence_bounded(kg):
    exp = kg.expand("Stripe Radar Connect Billing Tax fraud marketplace europe payments")
    assert 0.0 <= exp.confidence <= 1.0


# =========================================================================
# Edge cases
# =========================================================================
def test_empty_query(kg):
    exp = kg.expand("")
    assert exp.matched_scenarios == []
    assert exp.matched_products == []


def test_case_insensitive(kg):
    lower = kg.expand("stripe radar fraud")
    upper = kg.expand("STRIPE RADAR FRAUD")
    assert lower.matched_products == upper.matched_products
    assert lower.matched_scenarios == upper.matched_scenarios
