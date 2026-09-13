"""
Entity Linking and Graph Expansion.

The model links a question to the knowledge graph's vocabulary by naming
`products` and `topics` when it calls the search tool — both are enumerated
from the graph, so it can only name things that exist. The graph then widens
the search one hop: from each linked product to its integration and cross-sell
neighbours, and from each topic to the products that point at it. The result is
a scalar filter for both retrieval legs (ADR 0004).

When the model names nothing, a keyword pass over the question links products
by name so that recall does not fall to zero; that pass is a fallback, never
the first choice (ADR 0001 — the model decides).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.retrieval.graph import KnowledgeGraph

# Phrases that name a product unambiguously, for the keyword fallback only. Because the
# fallback narrows the filter, everyday words that merely overlap a product name
# ("link", "connect", "platform", "elements") are deliberately absent.
FALLBACK_PHRASES: dict[str, str] = {
    "checkout": "checkout",
    "payment link": "payment_links",
    "payment links": "payment_links",
    "stripe elements": "elements",
    "payment element": "elements",
    "terminal": "terminal",
    "card reader": "terminal",
    "tap to pay": "terminal",
    "radar": "radar",
    "fraud": "radar",
    "dispute": "radar",
    "chargeback": "radar",
    "stripe link": "link",
    "stripe connect": "connect",
    "marketplace": "connect",
    "connected account": "connect",
    "billing": "billing",
    "subscription": "subscriptions",
    "subscriptions": "subscriptions",
    "recurring": "subscriptions",
    "invoice": "invoicing",
    "invoicing": "invoicing",
    "tax": "tax",
    "vat": "tax",
    "gst": "tax",
    "revenue recognition": "revenue_recognition",
    "asc 606": "revenue_recognition",
    "ifrs": "revenue_recognition",
    "sigma": "sigma",
    "data pipeline": "data_pipeline",
    "warehouse": "data_pipeline",
    "payment method": "payment_methods",
    "payment methods": "payment_methods",
    "apple pay": "payment_methods",
    "google pay": "payment_methods",
    "klarna": "payment_methods",
    "ach": "payment_methods",
    "sepa": "payment_methods",
}


@dataclass(frozen=True)
class Vocabulary:
    products: tuple[str, ...]
    topics: tuple[str, ...]
    labels: dict[str, str]  # id -> human name, for tool descriptions


@dataclass
class Linked:
    products: list[str] = field(default_factory=list)  # what the model (or the fallback) named
    topics: list[str] = field(default_factory=list)
    expanded_products: list[str] = field(default_factory=list)  # products + one hop
    fallback: bool = False  # True when the keyword pass supplied the products


def vocabulary(kg: KnowledgeGraph) -> Vocabulary:
    products = tuple(sorted(kg.ids_of_type("product")))
    topics = tuple(kg.topic_ids())
    labels = {i: kg.name(i) for i in (*products, *topics)}
    return Vocabulary(products=products, topics=topics, labels=labels)


def keyword_products(question: str) -> list[str]:
    """Products whose names or common aliases appear in the question. Fallback only."""
    text = question.lower()
    found: list[str] = []
    for alias, product in FALLBACK_PHRASES.items():
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", text) and product not in found:
            found.append(product)
    return found


def link(kg: KnowledgeGraph, question: str, products: list[str], topics: list[str]) -> Linked:
    """Validate the model's entities against the graph and expand one hop."""
    known_products = set(kg.ids_of_type("product"))
    known_topics = set(kg.topic_ids())

    linked = Linked(
        products=[p for p in dict.fromkeys(products) if p in known_products],
        topics=[t for t in dict.fromkeys(topics) if t in known_topics],
    )
    if not linked.products and not linked.topics:
        linked.products = keyword_products(question)
        linked.fallback = True

    expanded: dict[str, None] = dict.fromkeys(linked.products)
    for product in linked.products:
        expanded.update(dict.fromkeys(kg.related_products(product)))
    for topic in linked.topics:
        expanded.update(dict.fromkeys(kg.products_for(topic)))
    linked.expanded_products = list(expanded)
    return linked


def filter_expr(linked: Linked) -> str:
    """The Milvus scalar filter shared by both legs. Public-only is always part of it."""
    clauses = []
    if linked.expanded_products:
        quoted = ", ".join(f'"{p}"' for p in linked.expanded_products)
        clauses.append(f"product in [{quoted}]")
    clauses.append('access_level == "public"')  # belt and braces: only public chunks are indexed anyway
    return " and ".join(clauses)
