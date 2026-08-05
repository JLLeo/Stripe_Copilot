"""
Escalation Gating — Strict evidence-based escalation decisions.

Principle: escalate only when BOTH conditions are met:
  A. The scenario is escalation-eligible (has triggers defined)
  B. The query or customer data contains concrete trigger evidence

Generic questions like "What is Stripe Connect?" NEVER escalate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.database import get_customer
from app.skills import get_skill


@dataclass
class EscalationResult:
    should_escalate: bool = False
    escalation_team: str | None = None
    reason: str = ""
    evidence: str = ""


# ---------------------------------------------------------------------------
# Team routing by trigger category
# ---------------------------------------------------------------------------
TEAM_ROUTING: dict[str, str] = {
    # Connect — only on explicit complex requests
    "custom onboarding": "Connect Specialist",
    "cross-border payout": "Connect Specialist",
    "KYC verification": "Connect Specialist",
    "multi-party payment flow": "Connect Specialist",
    # Pricing — only on explicit custom/enterprise pricing requests
    "custom pricing": "Deal Desk / Pricing Team",
    "volume discount": "Deal Desk / Pricing Team",
    "enterprise pricing": "Enterprise Sales",
    "IC+ pricing": "Deal Desk / Pricing Team",
    "interchange plus": "Deal Desk / Pricing Team",
    # Security — only on explicit document requests
    "SOC report": "Security & Compliance",
    "SOC 2": "Security & Compliance",
    "penetration test": "Security & Compliance",
    "pen test": "Security & Compliance",
    "AOC": "Security & Compliance",
    "security questionnaire": "Security & Compliance",
    # Tax — only on explicit filing/registration requests
    "filing": "Tax Team",
    "registration": "Tax Team",
    "tax return": "Tax Team",
    "VAT return": "Tax Team",
    # Fraud — only on explicit distress signals
    "dispute rate too high": "Fraud / Risk Team",
    "disputes are out of control": "Fraud / Risk Team",
    "chargeback problem": "Fraud / Risk Team",
    "help with disputes": "Fraud / Risk Team",
    "losing money to fraud": "Fraud / Risk Team",
    "fraud is out of control": "Fraud / Risk Team",
    # Enterprise — only on explicit contract/SLA mentions
    "enterprise contract": "Enterprise Sales",
    "SLA": "Enterprise Sales",
    # Escalation requests — only on explicit multi-word phrases
    "talk to a human": "Sales Ops / Human Agent",
    "speak to a human": "Sales Ops / Human Agent",
    "speak to a real person": "Sales Ops / Human Agent",
    "speak to your manager": "Sales Ops / Human Agent",
    "talk to your supervisor": "Sales Ops / Human Agent",
    "file a complaint": "Sales Ops / Human Agent",
    "not a robot": "Sales Ops / Human Agent",
    "connect me to": "Sales Ops / Human Agent",
    "connect me with": "Sales Ops / Human Agent",
    "put me in touch": "Sales Ops / Human Agent",
    "get me in touch": "Sales Ops / Human Agent",
    "someone who handles": "Sales Ops / Human Agent",
    "someone who can help": "Sales Ops / Human Agent",
}


def check_escalation(
    scenario: str,
    customer_id: str = "",
    query: str = "",
) -> EscalationResult:
    """
    Decide whether to escalate based on scenario triggers + evidence.

    Args:
        scenario: Classified scenario ID (e.g., 'pricing_negotiation').
        customer_id: Optional customer ID for volume/risk DB checks.
        query: The original user question for keyword scanning.

    Returns:
        EscalationResult with decision, team, reason, and evidence.
    """
    skill = get_skill(scenario)

    # --- Gate A: Is this scenario escalation-eligible? ---
    triggers = skill.escalation_triggers
    if not triggers:
        return EscalationResult(
            should_escalate=False,
            reason=f"Scenario '{scenario}' is not escalation-eligible by default.",
        )

    # --- Gate B: Does the query contain trigger evidence? ---
    query_lower = query.lower() if query else ""
    matched_triggers: list[str] = []
    for trigger in triggers:
        if trigger.lower() in query_lower:
            matched_triggers.append(trigger)

    # --- Volume-based escalation (data-driven) ---
    volume_triggered = False
    if customer_id:
        profile = get_customer(customer_id)
        if profile:
            volume = profile.get("annual_payment_volume") or 0
            if scenario == "pricing_negotiation" and volume > 1_000_000:
                volume_triggered = True
                matched_triggers.append(f"annual_volume_${volume:,.0f}")
            # Enterprise threshold: only for pricing-related scenarios
            _pricing_scenarios = ("pricing_negotiation", "saas_billing")
            if volume > 10_000_000 and scenario in _pricing_scenarios:
                return EscalationResult(
                    should_escalate=True,
                    escalation_team="Enterprise Sales",
                    reason="Customer annual volume exceeds $10M enterprise threshold.",
                    evidence=f"annual_payment_volume = ${volume:,.0f}",
                )

    # --- Decision ---
    if not matched_triggers:
        return EscalationResult(
            should_escalate=False,
            reason=(
                f"Scenario '{scenario}' is escalation-eligible but no trigger "
                f"matched. Triggers: {list(triggers)}"
            ),
        )

    # Route to the right team based on matched triggers
    teams = set()
    for trigger in matched_triggers:
        t = TEAM_ROUTING.get(trigger)
        if t:
            teams.add(t)

    if not teams:
        return EscalationResult(
            should_escalate=False,
            reason=f"Triggers matched ({matched_triggers}) but no team routing found.",
        )

    team = teams.pop() if len(teams) == 1 else " / ".join(sorted(teams))
    return EscalationResult(
        should_escalate=True,
        escalation_team=team,
        reason=f"Evidence matched triggers: {matched_triggers}",
        evidence=f"query_keywords={matched_triggers}"
        + (f", customer_volume_triggered=True" if volume_triggered else ""),
    )


def escalate_with_context(
    scenario: str,
    query: str,
    conversation_summary: str,
) -> EscalationResult:
    """
    Let LLM decide if escalation is warranted based on multi-turn conversation context.
    Only called when rules miss but conversation history exists.
    """
    from dotenv import load_dotenv
    from openai import OpenAI
    import json as _json

    load_dotenv()
    skill = get_skill(scenario)

    client = OpenAI()
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": (
                "You are an escalation gatekeeper. Be EXTREMELY strict.\n"
                "ONLY escalate if the user EXPLICITLY demands a human:\n"
                "'connect me to a person', 'I want to talk to someone', "
                "'transfer me to your manager', 'speak to a human'.\n\n"
                "Do NOT escalate for ANY of these:\n"
                "- Account lookups ('pull up my account', 'what are we using')\n"
                "- Product questions, feature explanations\n"
                "- Pricing inquiries, policy questions\n"
                "- Any request the AI can handle with its tools\n\n"
                f"Escalation triggers: {list(skill.escalation_triggers)}\n\n"
                "Return JSON: {\"escalate\": true/false, \"team\": \"null or team\", "
                "\"reason\": \"brief\"}"
            )},
            {"role": "user", "content": (
                f"Conversation:\n{conversation_summary[:400]}\n\n"
                f"Latest message: {query}\n\n"
                "Does the user EXPLICITLY demand a human? YES or NO?"
            )},
        ],
        temperature=0.0, max_tokens=150,
    )
    raw = resp.choices[0].message.content or "{}"
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = _json.loads(raw)
        if data.get("escalate"):
            return EscalationResult(
                should_escalate=True,
                escalation_team=data.get("team") or "Sales Ops",
                reason=data.get("reason", "LLM determined escalation warranted based on conversation context."),
                evidence=f"context_aware_llm, query='{query[:100]}'",
            )
    except (_json.JSONDecodeError, ValueError):
        pass
    return EscalationResult(
        should_escalate=False,
        reason="LLM determined no escalation needed based on context.",
    )
