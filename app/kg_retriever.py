"""
KG Retriever — Query Expansion
===============================
Takes a raw user query, matches it against the knowledge graph,
and returns an expanded filter payload for Milvus metadata filtering.

Flow:
  user_query → extract entities → KG traversal → filter dict
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.kg_builder import KnowledgeGraph, get_knowledge_graph


@dataclass
class QueryExpansion:
    """Result of expanding a user query using the knowledge graph."""

    raw_query: str
    matched_scenarios: list[str] = field(default_factory=list)
    matched_products: list[str] = field(default_factory=list)
    matched_methods: list[str] = field(default_factory=list)
    matched_geos: list[str] = field(default_factory=list)
    related_products: list[str] = field(default_factory=list)  # KG-expanded
    should_escalate: bool = False
    escalation_team: str | None = None
    confidence: float = 0.5

    @property
    def all_products(self) -> list[str]:
        """Deduplicated union of matched + related products."""
        return list(dict.fromkeys(self.matched_products + self.related_products))


class KGRetriever:
    """Expands user queries by traversing the knowledge graph."""

    # Product name → ID fuzzy mapping (for matching user mentions)
    PRODUCT_ALIASES: dict[str, str] = {
        "checkout": "checkout",
        "payment link": "payment_links",
        "payment links": "payment_links",
        "elements": "elements",
        "terminal": "terminal",
        "radar": "radar",
        "link": "link",
        "connect": "connect",
        "billing": "billing",
        "subscription": "subscriptions",
        "subscriptions": "subscriptions",
        "invoice": "invoicing",
        "invoicing": "invoicing",
        "tax": "tax",
        "revenue recognition": "revenue_recognition",
        "asc 606": "revenue_recognition",
        "ifrs": "revenue_recognition",
        "sigma": "sigma",
        "data pipeline": "data_pipeline",
        "fraud": "radar",
        "payment": "payments",
        "payments": "payments",
        "payment methods": "payment_methods",
        "payment method": "payment_methods",
        "wallet": "link",
    }

    GEO_KEYWORDS: dict[str, str] = {
        "europe": "eu",
        "european": "eu",
        "eu": "eu",
        "us": "us",
        "united states": "us",
        "america": "us",
        "uk": "uk",
        "britain": "uk",
        "asia": "apac",
        "apac": "apac",
        "china": "cn",
        "latin america": "latam",
        "latam": "latam",
        "brazil": "latam",
        "mexico": "latam",
        "international": "global",
        "global": "global",
    }

    def __init__(self, kg: KnowledgeGraph | None = None):
        self.kg = kg or get_knowledge_graph()

    # ------------------------------------------------------------------
    def expand(self, query: str) -> QueryExpansion:
        """Main entry point: expand a user query into a filter payload."""
        q_lower = query.lower()
        result = QueryExpansion(raw_query=query)

        # Step 1 — Match sales scenarios by keyword patterns
        scenario_patterns = self.kg.get_scenario_patterns()
        for scenario_id, patterns in scenario_patterns.items():
            for pattern in patterns:
                if pattern in q_lower:
                    result.matched_scenarios.append(scenario_id)
                    break

        # Step 2 — Match products by name / alias
        for alias, product_id in self.PRODUCT_ALIASES.items():
            if alias in q_lower and product_id not in result.matched_products:
                result.matched_products.append(product_id)

        # Step 3 — Match geographies
        matched_geo_ids: list[str] = []
        for keyword, geo_id in self.GEO_KEYWORDS.items():
            if keyword in q_lower and geo_id not in matched_geo_ids:
                matched_geo_ids.append(geo_id)
                result.matched_geos.append(geo_id)

        # Step 4 — From matched geographies, find payment methods available there
        if matched_geo_ids:
            result.matched_methods = self._methods_for_geos(matched_geo_ids)

        # Step 5 — KG traversal: expand 1-hop from matched products
        result.related_products = self._expand_products(
            result.matched_products, result.matched_scenarios
        )

        # Step 6 — Escalation check
        for scenario_id in result.matched_scenarios:
            edge_data = self.kg.graph.get_edge_data(scenario_id, None)
            if edge_data is None:
                # check incoming edges with requires_escalation predicate
                for _, neighbor, ed in self.kg.graph.out_edges(scenario_id, data=True):
                    if ed.get("predicate") == "requires_escalation":
                        result.should_escalate = True
                        node = self.kg.get_node(neighbor)
                        if node:
                            result.escalation_team = node.get("name", neighbor)

        # Also check pricing and security scenarios
        if "pricing_negotiation" in result.matched_scenarios:
            result.should_escalate = True
            result.escalation_team = "Deal Desk / Pricing Team"
        if "security_compliance" in result.matched_scenarios:
            result.should_escalate = True
            result.escalation_team = "Security & Compliance"

        # Compute confidence
        result.confidence = self._compute_confidence(result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _expand_products(
        self, matched_products: list[str], matched_scenarios: list[str]
    ) -> list[str]:
        """Traverse KG to find related products not directly mentioned."""
        expanded: set[str] = set()

        # From scenarios → products via used_for
        for scenario_id in matched_scenarios:
            for product_id in self.kg.get_products_for_scenario(scenario_id):
                expanded.add(product_id)

        # From matched products → 1-hop neighbors (integrates_with, cross_sell)
        for product_id in matched_products:
            for related in self.kg.get_related_products(product_id, radius=1):
                expanded.add(related)

        # Remove products already directly matched
        return [p for p in expanded if p not in matched_products]

    def _methods_for_geos(self, geo_ids: list[str]) -> list[str]:
        """Find payment methods available in given geographies."""
        methods: set[str] = set()
        all_methods = self.kg.get_nodes_by_type("payment_method")
        for method in all_methods:
            method_regions = method.get("regions", [])
            if any(g in method_regions for g in geo_ids) or "global" in method_regions:
                methods.add(method["id"])
        return list(methods)

    def _compute_confidence(self, result: QueryExpansion) -> float:
        """Simple heuristic confidence score."""
        score = 0.3  # base
        if result.matched_scenarios:
            score += 0.2
        if result.matched_products:
            score += 0.2
        if result.related_products:
            score += 0.15
        if result.matched_geos:
            score += 0.1
        if result.matched_methods:
            score += 0.05
        return min(score, 1.0)

    # ------------------------------------------------------------------
    # Build Milvus filter expression from expansion
    # ------------------------------------------------------------------
    def build_filter_expr(self, expansion: QueryExpansion) -> str | None:
        """
        Convert a QueryExpansion into a Milvus scalar filter expression.

        Returns a string like:
          'product in ["checkout","billing","tax"]'
        or None if no filter can be generated.
        """
        products = expansion.all_products
        if not products:
            return None

        # Escape strings for Milvus expression
        quoted = ", ".join(f'"{p}"' for p in products)
        return f"product in [{quoted}]"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_retriever_instance: KGRetriever | None = None


def get_kg_retriever() -> KGRetriever:
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = KGRetriever()
    return _retriever_instance


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    retriever = KGRetriever()

    test_queries = [
        "Our marketplace needs seller onboarding and payouts",
        "SaaS platform with subscription billing in Europe",
        "How do I prevent fraud on my ecommerce store?",
        "We need SOC 2 compliance for enterprise customers",
        "I want to sell online without coding — fast setup",
        "We have $5M annual volume and need custom pricing",
    ]

    for q in test_queries:
        exp = retriever.expand(q)
        print(f"\n{'='*60}")
        print(f"Query:  {q}")
        print(f"Scenarios: {exp.matched_scenarios}")
        print(f"Products:  {exp.matched_products}")
        print(f"Related:   {exp.related_products}")
        print(f"Geos:      {exp.matched_geos}")
        print(f"Methods:   {exp.matched_methods[:6]}{'...' if len(exp.matched_methods) > 6 else ''}")
        print(f"Escalate:  {exp.should_escalate} → {exp.escalation_team}")
        print(f"Confidence: {exp.confidence:.2f}")
        print(f"Filter:    {retriever.build_filter_expr(exp)}")
