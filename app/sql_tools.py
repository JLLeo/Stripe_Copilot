"""
SQL Tools — parameterised query functions for the ReAct agent.

All functions accept simple types and return plain dicts/lists
so they can be wrapped as LangChain Tools with clean signatures.
"""

from __future__ import annotations

from app.database import (
    get_active_policies,
    get_connection,
    get_customer,
    get_customer_product_usage,
)


def lookup_customer(customer_id: str) -> dict:
    """
    Get full customer profile.

    Returns:
        dict with keys: customer_name, company_stage, industry, use_case,
        business_model, country, annual_payment_volume, monthly_transactions,
        average_order_value, primary_pain_point, fraud_risk_level, integration_maturity
        — or {"error": "..."} if not found.
    """
    profile = get_customer(customer_id)
    if profile is None:
        return {"error": f"Customer '{customer_id}' not found in database."}

    # Filter to key fields the agent cares about
    fields = [
        "customer_name", "company_stage", "industry", "use_case",
        "business_model", "country", "annual_payment_volume",
        "monthly_transactions", "average_order_value",
        "primary_pain_point", "fraud_risk_level", "integration_maturity",
    ]
    return {k: profile.get(k) for k in fields}


def lookup_product_usage(customer_id: str) -> list[dict]:
    """
    List products the customer is currently using.

    Returns:
        List of {product_name, product_group, usage_status, monthly_volume,
                  monthly_revenue, adoption_level}
    """
    rows = get_customer_product_usage(customer_id)
    return [
        {
            "product_name": r.get("product_name", ""),
            "product_group": r.get("product_group", ""),
            "usage_status": r.get("usage_status", ""),
            "monthly_volume": r.get("monthly_volume"),
            "monthly_revenue": r.get("monthly_revenue"),
            "adoption_level": r.get("adoption_level", ""),
        }
        for r in rows
    ]


def lookup_policy(product_area: str | None = None) -> list[dict]:
    """
    Retrieve active sales policies, optionally filtered by area.

    Valid areas: 'pricing', 'security', 'compliance', 'connect',
    'billing', 'fraud', etc.

    Returns:
        List of {policy_area, policy_title, policy_summary, escalation_team}
    """
    rows = get_active_policies(product_area)
    return [
        {
            "policy_area": r.get("policy_area", ""),
            "policy_title": r.get("policy_title", ""),
            "policy_summary": r.get("policy_summary", ""),
            "escalation_team": r.get("escalation_team", ""),
        }
        for r in rows
    ]


def search_customers_by_industry(industry: str) -> list[dict]:
    """Find customers in a given industry (for prospecting)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT customer_id, customer_name, company_stage, annual_payment_volume "
        "FROM customers WHERE industry LIKE ?",
        (f"%{industry}%",),
    ).fetchall()
    return [dict(r) for r in rows]


def get_customer_interactions(customer_id: str, limit: int = 5) -> list[dict]:
    """Return recent interactions for a customer."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT interaction_date, channel, customer_question, detected_intent,
               mentioned_products, follow_up_action
        FROM sales_interactions
        WHERE customer_id = ?
        ORDER BY interaction_date DESC
        LIMIT ?
        """,
        (customer_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
