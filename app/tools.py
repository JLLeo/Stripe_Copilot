"""
Tool Registry — LangChain Tools wrapping KG + Milvus + SQL.

Each tool has:
  - A typed function signature (for LLM function-calling)
  - A docstring describing when to use it
  - Access to the shared KG / Milvus / SQL singletons

Output format
-------------
Every tool returns JSON. Structured output means downstream code can read
fields directly instead of parsing formatted prose, and the LLM can cite
sources accurately. `parse_tool_output()` recovers the dict from a raw
tool result string.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from app.kg_builder import get_knowledge_graph
from app.kg_retriever import get_kg_retriever
from app.milvus_retriever import get_milvus_retriever
from app.sql_tools import (
    get_customer_interactions,
    lookup_customer,
    lookup_policy,
    lookup_product_usage,
)


# ======================================================================
# Structured output helpers
# ======================================================================
def _ok(tool: str, **payload: Any) -> str:
    """Serialize a successful tool result."""
    return json.dumps({"tool": tool, "ok": True, **payload}, ensure_ascii=False, default=str)


def _empty(tool: str, message: str, **payload: Any) -> str:
    """Serialize a successful-but-empty tool result."""
    return json.dumps(
        {"tool": tool, "ok": True, "results": [], "message": message, **payload},
        ensure_ascii=False, default=str,
    )


def parse_tool_output(output: str) -> dict:
    """
    Recover the structured dict from a tool's return value.

    Returns {"ok": False, "raw": ...} when the output is not valid JSON
    (e.g. an ERROR: string produced by the pipeline's exception handler).
    """
    try:
        data = json.loads(output)
        return data if isinstance(data, dict) else {"ok": False, "raw": output}
    except (json.JSONDecodeError, TypeError):
        return {"ok": False, "raw": output}


# ======================================================================
# Core Tools
# ======================================================================

@tool
def search_product_info(query: str, top_k: int = 5) -> str:
    """
    Search for Stripe product features, capabilities, integrations,
    and use cases. Use this to learn what a product does or how it works.

    For pricing/cost: use lookup_pricing_tool instead.
    For policies/procedures: use lookup_policy_tool instead.
    Customer data is already auto-loaded — do not re-query.

    Args:
        query: Natural-language search query.
        top_k: Number of results (default 5).
    """
    milvus = get_milvus_retriever()
    kg = get_kg_retriever()
    expansion = kg.expand(query)

    resp = milvus.search(query, top_k=top_k, use_kg_filter=True, access_level="public")

    if not resp.results:
        return _empty(
            "search_product_info",
            "No matching documents found in the Stripe knowledge base.",
            query=query,
        )

    return _ok(
        "search_product_info",
        query=query,
        matched_products=expansion.all_products,
        results=[
            {
                "rank": i + 1,
                "product": r.product,
                "source": r.source_file,
                "relevance": round(r.score, 3),
                "text": r.text.strip(),
            }
            for i, r in enumerate(resp.results)
        ],
        note=(
            "Covers product features and capabilities only. "
            "For pricing rates, call lookup_pricing_tool."
        ),
    )


@tool
def lookup_customer_tool(customer_id: str) -> str:
    """
    Look up a customer's profile, including their industry, payment volume,
    business model, and pain points. Use this when you need context about
    who the customer is before making a recommendation.

    Args:
        customer_id: The customer's ID (e.g., 'C001').
    """
    profile = lookup_customer(customer_id)
    if "error" in profile:
        return _empty("lookup_customer_tool", profile["error"], customer_id=customer_id)

    return _ok(
        "lookup_customer_tool",
        customer_id=customer_id,
        profile={
            "name": profile.get("customer_name"),
            "stage": profile.get("company_stage"),
            "industry": profile.get("industry"),
            "use_case": profile.get("use_case"),
            "business_model": profile.get("business_model"),
            "country": profile.get("country"),
            "annual_payment_volume": profile.get("annual_payment_volume") or 0,
            "monthly_transactions": profile.get("monthly_transactions"),
            "average_order_value": profile.get("average_order_value"),
            "primary_pain_point": profile.get("primary_pain_point"),
            "fraud_risk_level": profile.get("fraud_risk_level"),
            "integration_maturity": profile.get("integration_maturity"),
        },
    )


@tool
def lookup_product_usage_tool(customer_id: str) -> str:
    """
    Check which Stripe products a customer is already using, including
    volume and adoption level. Use this before recommending new products.

    Args:
        customer_id: The customer's ID (e.g., 'C001').
    """
    rows = lookup_product_usage(customer_id)
    if not rows:
        return _empty(
            "lookup_product_usage_tool",
            f"Customer {customer_id} has no active Stripe products on record.",
            customer_id=customer_id,
        )

    return _ok(
        "lookup_product_usage_tool",
        customer_id=customer_id,
        results=[
            {
                "product": r["product_name"],
                "product_group": r["product_group"],
                "adoption_level": r["adoption_level"],
                "monthly_revenue": r.get("monthly_revenue") or 0,
            }
            for r in rows
        ],
    )


@tool
def lookup_pricing_tool(product_area: str = "") -> str:
    """
    Return Stripe's CURRENT pricing — rates, tiers, volume discounts.
    Use this for ANY question about how much a Stripe product costs.
    This returns actual pricing data, unlike search_product_info which only
    returns product features. Do NOT use search_product_info for pricing.

    Args:
        product_area: 'billing', 'connect', 'payments', 'terminal', 'tax',
                      'radar', or '' for all.
    """
    from pathlib import Path

    # Read pricing KB docs directly — not via Milvus
    pricing_dir = Path(__file__).resolve().parent.parent / "knowledge_base" / "pricing"
    sources = []

    # Always include the main pricing overview
    overview = pricing_dir / "pricing_overview.md"
    if overview.exists():
        text = overview.read_text(encoding="utf-8")
        # Extract the body (after frontmatter, starting from ## Summary)
        body_start = text.find("## Summary")
        if body_start > 0:
            sources.append(("Stripe Pricing Overview", text[body_start:].strip()))

    # If a specific area is requested, include custom pricing policy
    if product_area:
        policy = pricing_dir / "custom_pricing_policy.md"
        if policy.exists():
            text = policy.read_text(encoding="utf-8")
            # Only include public-relevant sections (Summary + Key Capabilities)
            body_start = text.find("## Summary")
            if body_start > 0:
                body = text[body_start:].strip()
                # Stop before internal-only sections
                cutoff = body.find("## Price")
                if cutoff > 0:
                    body = body[:cutoff].strip()
                sources.append(("Custom Pricing Policy", body))

    if not sources:
        return _empty(
            "lookup_pricing_tool",
            "Pricing documentation not found.",
            product_area=product_area,
        )

    return _ok(
        "lookup_pricing_tool",
        product_area=product_area or "all",
        results=[
            {
                "title": title,
                "source": "knowledge_base/pricing",
                "text": content[:1200] + ("\n...(truncated)" if len(content) > 1200 else ""),
            }
            for title, content in sources
        ],
        note="For internal pricing policies and escalation rules, call lookup_policy_tool.",
    )


@tool
def lookup_policy_tool(policy_area: str = "") -> str:
    """
    Look up active internal sales policies, escalation rules, and compliance
    procedures from the SQL database (not the knowledge base).
    Use this for questions about: escalation procedures, document request
    processes (SOC reports, AOC), regulatory requirements, or sales policies.
    Do NOT use search_product_info for policy/procedure questions.

    Args:
        policy_area: Filter by area, e.g. 'pricing', 'security', 'compliance'.
    """
    rows = lookup_policy(policy_area if policy_area else None)
    if rows:
        return _ok(
            "lookup_policy_tool",
            policy_area=policy_area or "all",
            source="sql",
            results=[
                {
                    "area": r["policy_area"],
                    "title": r["policy_title"],
                    "summary": r["policy_summary"],
                    "escalate_to": r["escalation_team"],
                }
                for r in rows
            ],
        )

    # Fallback: search KB for policy-related documents
    milvus = get_milvus_retriever()
    kb_query = f"policy {policy_area}" if policy_area else "policy"
    resp = milvus.search(kb_query, top_k=3, use_kg_filter=False)
    if resp.results:
        return _ok(
            "lookup_policy_tool",
            policy_area=policy_area or "all",
            source="knowledge_base",
            note=f"No SQL policies for '{policy_area or 'all'}'; showing KB matches.",
            results=[
                {"source": r.source_file, "relevance": round(r.score, 3), "text": r.text.strip()}
                for r in resp.results
            ],
        )

    return _empty(
        "lookup_policy_tool",
        f"No policies found in database or knowledge base"
        f"{' for ' + policy_area if policy_area else ''}.",
        policy_area=policy_area or "all",
    )


@tool
def check_escalation_tool(scenario: str, customer_id: str = "", query: str = "") -> str:
    """
    Determine if the current scenario requires escalation to a specialist
    team. Returns the escalation decision with reasoning.

    Args:
        scenario: The classified scenario (e.g., 'pricing_negotiation').
        customer_id: Optional customer ID for volume/risk checks.
        query: The original customer question for keyword scanning.
    """
    from app.escalation import check_escalation

    result = check_escalation(scenario, customer_id, query)
    return _ok(
        "check_escalation_tool",
        scenario=scenario,
        should_escalate=result.should_escalate,
        escalation_team=result.escalation_team,
        reason=result.reason,
        evidence=result.evidence,
    )


# ======================================================================
# Registry — all tools the LLM can call
# ======================================================================

ALL_TOOLS = [
    search_product_info,
    lookup_customer_tool,
    lookup_product_usage_tool,
    lookup_pricing_tool,
    lookup_policy_tool,
    check_escalation_tool,
]

# Map tool name → tool object for quick lookup
TOOL_BY_NAME = {t.name: t for t in ALL_TOOLS}


def get_tools_for_skill(required: tuple[str, ...], optional: tuple[str, ...]) -> list:
    """
    Return the subset of tools available for a given skill config.
    LLM can ONLY see/call these tools during this scenario.
    """
    allowed = set(required) | set(optional)
    return [t for t in ALL_TOOLS if t.name in allowed]
