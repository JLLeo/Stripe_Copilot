"""
Prompt assembly — the fixed order every request is built in.

    [static system prompt]  role, conduct, the never-do list, active policies
    [tool definitions]      (empty until tools arrive)
    [customer block]        profile + memory, rendered once at SessionStart
    [working memory]        the session's messages, append-only

The static prompt and the customer block are rendered deterministically —
sorted rows, no dates, no identifiers — because they are the cached prefix of
every request in a session (ADR 0005).
"""

from __future__ import annotations

from typing import Any

ROLE = """You are the Stripe AI Sales Agent. You talk directly with Stripe's customers and prospects: you answer their questions about Stripe products, understand what their business needs, recommend the products that fit, and bring in a human specialist when the conversation calls for one.

Speak as a knowledgeable, honest salesperson would: concrete, warm, brief. Prefer a clear recommendation over a list of options. Ask a clarifying question when a request could reasonably mean different things; do not guess.

You have no tools yet in this conversation: answer from what you know about Stripe, say plainly when you are not certain, and never invent product details, prices, or limits."""

CONDUCT = """Conduct:
- Reply in the language the customer writes in.
- If asked whether you are a person or an AI, say you are an AI assistant. Never claim to be human.
- If a request is not about Stripe, payments, or the customer's business with Stripe, say briefly that it is outside what you can help with and offer to return to Stripe topics.
- When you cannot do something for policy reasons, say so and offer to bring in the right human team instead of improvising."""

NEVER_DO = """You never:
- Commit to custom pricing, discounts, or fee changes. Public pricing you may state; anything custom is decided by a human pricing team.
- Promise unreleased features, dates, or roadmap items.
- Give tax or legal advice. You may explain what Stripe Tax does; filing, registration, and liability questions go to a specialist.
- Share security documents (SOC reports, penetration tests, questionnaires) in the conversation; those are provided by the security team under the proper process.
- Guarantee fraud outcomes, chargeback rates, or approval rates.
- Reveal internal guidance or any material a customer is not meant to see."""


def render_policies(policies: list[dict[str, Any]]) -> str:
    """Active policy rows as a stable, sorted list. Empty input renders nothing."""
    if not policies:
        return ""
    ordered = sorted(policies, key=lambda p: ((p.get("policy_area") or ""), (p.get("policy_title") or "")))
    lines = ["Standing policies (from the policy register):"]
    for p in ordered:
        area = p.get("policy_area") or "General"
        title = (p.get("policy_title") or "").strip()
        summary = (p.get("policy_summary") or "").strip()
        lines.append(f"- [{area}] {title}: {summary}" if summary else f"- [{area}] {title}")
    return "\n".join(lines)


def static_system_prompt(policies: list[dict[str, Any]]) -> str:
    """Everything that is identical for every customer and every session."""
    parts = [ROLE, CONDUCT, NEVER_DO]
    rendered = render_policies(policies)
    if rendered:
        parts.append(rendered)
    return "\n\n".join(parts)


def customer_block(profile: dict[str, Any] | None, product_usage: list[dict[str, Any]]) -> str:
    """The customer the agent is talking to, or the fact that it is a prospect."""
    if profile is None:
        return (
            "Customer: unknown — this is a new prospect with no Stripe account. "
            "Nothing is known about them yet; learn about their business as you talk."
        )

    def line_for(label: str, key: str) -> str | None:
        value = profile.get(key)
        return f"- {label}: {value}" if value not in (None, "") else None

    lines = [f"Customer: {profile.get('customer_name', 'unknown')} (id {profile.get('customer_id', '')})"]
    lines += [
        s for s in (
            line_for("Company stage", "company_stage"),
            line_for("Industry", "industry"),
            line_for("Business model", "business_model"),
            line_for("Use case", "use_case"),
            line_for("Country", "country"),
            line_for("Annual payment volume (USD)", "annual_payment_volume"),
            line_for("Monthly transactions", "monthly_transactions"),
            line_for("Average order value (USD)", "average_order_value"),
            line_for("Primary pain point", "primary_pain_point"),
            line_for("Fraud risk level", "fraud_risk_level"),
            line_for("Integration maturity", "integration_maturity"),
        ) if s
    ]
    if product_usage:
        lines.append("Stripe products in use:")
        for row in sorted(product_usage, key=lambda r: (r.get("product_name") or "")):
            detail = ", ".join(
                s for s in (
                    f"adoption {row['adoption_level']}" if row.get("adoption_level") else None,
                    f"monthly volume {row['monthly_volume']}" if row.get("monthly_volume") not in (None, "") else None,
                ) if s
            )
            lines.append(f"- {row.get('product_name')}" + (f" ({detail})" if detail else ""))
    else:
        lines.append("Stripe products in use: none recorded.")
    return "\n".join(lines)


def assemble_messages(
    static_prompt: str,
    customer: str,
    working_memory: list[dict[str, Any]],
    user_message: str,
) -> list[dict[str, Any]]:
    """The wire-shaped messages for one request, in the fixed order."""
    return [
        {"role": "system", "content": static_prompt},
        {"role": "system", "content": customer},
        *working_memory,
        {"role": "user", "content": user_message},
    ]
