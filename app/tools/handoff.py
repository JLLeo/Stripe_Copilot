"""
Handoff — the agent passes the conversation to a human Team, with the
customer's confirmation.

`request_handoff(team, reason, evidence)` is a tool the model calls when the
customer asks for a person or a Policy reserves the matter for humans. Three
guardrails sit in front of it: `handoff_validity` (a real team, evidence the
customer or their profile actually supplied), `enterprise_volume` (a customer
above $10M a year always goes to Enterprise Sales), and
`handoff_confirmation`, which pauses the turn so the customer can say yes or
no — Claude Code's permission prompt, pointed at the customer. Only a
confirmation brings a team in; a decline is kept as a `declined` row so the
proposal is never acted on and the numbers add up, and nobody is contacted.
"""

from __future__ import annotations

import re
from typing import Any

from app import database
from app.database import CUSTOMER_PROFILE_FIELDS
from app.harness.hooks import Deny, HookEvent, HookRegistry, Pause, ToolUseContext
from app.harness.tools import Tool, ToolContext, ToolRegistry, ToolResult

ENTERPRISE_VOLUME = 10_000_000  # annual payment volume, USD, above which Enterprise Sales owns the relationship

# The seven canonical Teams and what each handles — this text is what the model reads.
TEAMS: dict[str, str] = {
    "Enterprise Sales": "customers above $10M in annual volume, enterprise contracts, SLAs, multi-entity or multi-year deals",
    "Deal Desk / Pricing": "custom pricing, discounts, interchange-plus, volume commitments, pricing comparisons against another processor",
    "Solutions Engineering": "Connect and platform architecture, payout design, migrations, complex integrations, local payment method availability",
    "Security & Compliance": "SOC and PCI reports, security questionnaires, penetration testing, data handling and residency, compliance approvals",
    "Tax Specialist": "tax liability, registration, filing, VAT/GST obligations, accounting and revenue recognition guidance",
    "Risk / Fraud": "fraud losses, dispute and chargeback problems, account risk reviews, acceptance-rate concerns",
    "Sales Representative": "the customer simply wants a person, or a commercial question no specialist team above covers",
}

# The policy register uses its own team names; each maps onto a canonical Team.
POLICY_TEAM_MAP: dict[str, str] = {
    "Sales Ops / Pricing Team": "Deal Desk / Pricing",
    "Deal Desk / Legal": "Enterprise Sales",
    "Solutions Engineering": "Solutions Engineering",
    "Security / Legal": "Security & Compliance",
    "Data Governance / Security": "Security & Compliance",
    "Compliance": "Security & Compliance",
    "Compliance / Legal": "Security & Compliance",
    "Risk / Legal": "Risk / Fraud",
    "Legal / Tax Specialist": "Tax Specialist",
    "Finance Specialist / Legal": "Tax Specialist",
    "Product / Legal": "Sales Representative",
    "Legal": "Sales Representative",
}


def team_for_policy(register_name: str) -> str:
    """The canonical Team behind a policy register entry; unknown names go to a human rep."""
    return POLICY_TEAM_MAP.get((register_name or "").strip(), "Sales Representative")


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------
_WORD = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")


def _whole(word: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) is not None


def _traceable(evidence: str, ctx: ToolUseContext) -> bool:
    """Evidence must come from what the customer said or what their profile holds — not from thin air.

    Two ways to qualify. From the conversation: the evidence is a passage of, or mostly
    made of whole words from, the customer's own messages. From the profile: it names at
    least one actual profile *value* (a number, a country, a business model …) and its
    words come from the profile as the model saw it. Field names alone never suffice, so
    "annual payment volume" cannot be manufactured from the schema.
    """
    needle = evidence.lower().strip()
    words = [w for w in _WORD.findall(needle) if len(w) >= 4]
    said = " ".join([
        ctx.turn.customer_message,
        *(m.get("content") or "" for m in database.load_messages(ctx.turn.session_id) if m["role"] == "user"),
    ]).lower()
    if needle and needle in said:
        return True
    if words and sum(_whole(w, said) for w in words) / len(words) >= 0.6:
        return True

    profile = database.get_customer(ctx.turn.customer_id) if ctx.turn.customer_id else None
    if not profile or not words:
        return False
    values = [str(v).lower() for v in profile.values() if v not in (None, "") and len(str(v)) >= 4]
    names_a_value = any(_whole(v, needle) for v in values)
    block = " ".join([*CUSTOMER_PROFILE_FIELDS.values(), *values]).lower()
    return names_a_value and sum(_whole(w, block) for w in words) / len(words) >= 0.6


def handoff_validity(ctx: ToolUseContext) -> Deny | None:
    if ctx.tool.name != "request_handoff":
        return None
    team = ctx.arguments.get("team", "")
    if team not in TEAMS:
        return Deny(f"{team!r} is not a team. Choose one of: {', '.join(TEAMS)}.")
    evidence = (ctx.arguments.get("evidence") or "").strip()
    if not evidence:
        return Deny("evidence is required: quote what the customer said, or the profile fact, that calls for a human.")
    if not _traceable(evidence, ctx):
        return Deny(
            "the evidence does not match anything the customer said or anything in their profile. "
            "Quote the customer's own words, or a fact from the profile, or ask them first."
        )
    return None


def enterprise_volume(ctx: ToolUseContext) -> Deny | None:
    if ctx.tool.name != "request_handoff" or not ctx.turn.customer_id:
        return None
    profile = database.get_customer(ctx.turn.customer_id) or {}
    volume = profile.get("annual_payment_volume") or 0
    if volume > ENTERPRISE_VOLUME and ctx.arguments.get("team") != "Enterprise Sales":
        return Deny(
            f"this customer's annual payment volume is ${volume:,}, above ${ENTERPRISE_VOLUME:,}: "
            "Enterprise Sales owns the relationship. Resubmit with team='Enterprise Sales'."
        )
    return None


def handoff_confirmation(ctx: ToolUseContext) -> Pause | None:
    """Every valid handoff waits for the customer. The pending row is the paused tool call."""
    if ctx.tool.name != "request_handoff":
        return None
    team, reason, evidence = (ctx.arguments[k] for k in ("team", "reason", "evidence"))
    handoff_id = database.create_pending_handoff(
        session_id=ctx.turn.session_id, customer_id=ctx.turn.customer_id,
        tool_call_id=ctx.call_id, team=team, reason=reason, evidence=evidence,
    )
    return Pause(
        event="handoff_pending",
        data={"handoff_id": handoff_id, "team": team, "reason": reason, "handles": TEAMS[team]},
        reply=(
            f"I can bring in our {team} team for this: {reason.rstrip('.')}. "
            "They would pick the conversation up from here. Shall I go ahead?"
        ),
    )


def register_guardrails(hooks: HookRegistry) -> None:
    hooks.register(HookEvent.PRE_TOOL_USE, handoff_validity)
    hooks.register(HookEvent.PRE_TOOL_USE, enterprise_volume)
    hooks.register(HookEvent.PRE_TOOL_USE, handoff_confirmation)


# ---------------------------------------------------------------------------
# Resolving the pause: the customer said yes or no
# ---------------------------------------------------------------------------
def resolve(session_id: str, accept: bool) -> tuple[str, ToolResult] | None:
    """Confirm or decline the session's pending handoff; returns (tool_call_id, result) or None if nothing is pending."""
    pending = database.pending_handoff(session_id)
    if pending is None:
        return None
    status = database.HANDOFF_CONFIRMED if accept else database.HANDOFF_DECLINED
    if not database.resolve_handoff(pending["id"], status):
        return None  # resolved concurrently by another request; that request appended the result
    if accept:
        payload: dict[str, Any] = {
            "status": status,
            "team": pending["team"],
            "handoff_id": pending["id"],
            "next": (
                f"The {pending['team']} team has the conversation and the reason; they will contact the customer. "
                "Tell the customer what happens next and offer to keep helping meanwhile."
            ),
        }
    else:
        payload = {
            "status": status,
            "team": pending["team"],
            "next": "The customer declined the handoff. Continue helping them yourself within policy; do not propose it again unless they ask.",
        }
    return pending["tool_call_id"], ToolResult.from_payload(payload)


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------
def request_handoff(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    # Never reached in a turn: handoff_confirmation pauses first, and `resolve` produces the result.
    return ToolResult.error("request_handoff must be confirmed by the customer before it runs.")


def register(registry: ToolRegistry) -> None:
    handles = "; ".join(f"{team} — {what}" for team, what in TEAMS.items())
    registry.register(Tool(
        name="request_handoff",
        description=(
            "Propose handing the conversation to a human team. Use it when the customer asks for a person, or "
            "when a policy reserves the matter for humans (custom pricing or discounts, security documents, tax "
            "liability or filing, enterprise contracts, complex Connect design, fraud losses). The customer is "
            "asked to confirm before anything is recorded. Teams: " + handles
        ),
        parameters={
            "type": "object",
            "properties": {
                "team": {"type": "string", "enum": list(TEAMS), "description": "The team that should take over."},
                "reason": {
                    "type": "string",
                    "description": (
                        "One sentence addressed to the customer on why a human is needed, e.g. "
                        "\"you'd like a custom rate on your volume\". It is shown to them verbatim."
                    ),
                },
                "evidence": {
                    "type": "string",
                    "description": "The customer's own words, or a profile fact, that calls for this handoff — quoted, not paraphrased.",
                },
            },
            "required": ["team", "reason", "evidence"],
            "additionalProperties": False,
        },
        run=request_handoff,
        cacheable=False,
    ))
