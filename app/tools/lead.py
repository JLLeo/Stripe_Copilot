"""
capture_lead — what the agent learned about a Prospect, written as the session's Lead.

A Prospect has no Customer Profile; the Lead is the record a colleague reads
before following up, so the prospect never has to repeat themselves. One Lead
per session: each call adds or corrects what it names and keeps everything else,
and the model gets the whole Lead back so it can see what is still missing.
"""

from __future__ import annotations

from typing import Any

from app import database
from app.database import LEAD_FIELDS
from app.harness.hooks import Deny, HookEvent, HookRegistry, ToolUseContext
from app.harness.tools import Tool, ToolContext, ToolRegistry, ToolResult


def capture_lead(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    fields: dict[str, Any] = {}
    ignored: list[str] = []  # a bad value never costs the good ones their write
    for key in LEAD_FIELDS:
        value = args.get(key)
        if key == "annual_volume_usd":
            if value in (None, ""):
                continue
            try:
                volume = int(round(float(value)))
            except (TypeError, ValueError):
                ignored.append("annual_volume_usd ignored: give a number of US dollars per year, e.g. 1200000")
                continue
            if volume < 0:
                ignored.append("annual_volume_usd ignored: it cannot be negative")
                continue
            fields[key] = volume
        elif isinstance(value, str) and value.strip():
            fields[key] = value.strip()
    products = args.get("recommended_products")
    if products is not None:
        if isinstance(products, list):
            products = [str(p).strip() for p in products if str(p).strip()] or None
        else:
            ignored.append("recommended_products ignored: give a list of product names")
            products = None
    if not fields and products is None:
        return ToolResult.error(
            "Nothing to capture yet: give at least one of " + ", ".join(LEAD_FIELDS) + " or recommended_products."
            + (" " + "; ".join(ignored) + "." if ignored else "")
        )
    lead = database.upsert_lead(ctx.session_id, fields, products)
    payload: dict[str, Any] = {"lead": lead, "still_unknown": [k for k in LEAD_FIELDS if lead.get(k) in (None, "")]}
    if ignored:
        payload["ignored"] = ignored
    return ToolResult.from_payload(payload)


def prospect_only(ctx: ToolUseContext) -> Deny | None:
    """A Lead is the record of a Prospect; a signed-in customer already has a profile."""
    if ctx.tool.name != "capture_lead" or not ctx.turn.customer_id:
        return None
    return Deny(
        "this customer is signed in and already has a profile (get_my_profile); leads are captured only for new "
        "prospects. Keep what they told you in the conversation and answer them directly."
    )


def register_guardrails(hooks: HookRegistry) -> None:
    hooks.register(HookEvent.PRE_TOOL_USE, prospect_only)


def register(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="capture_lead",
        description=(
            "Record what a new prospect has told you — company, business model, yearly payment volume, timeline, "
            "needs, how qualified they are — and the products you recommended, so a colleague can follow up without "
            "them repeating it. Call it as soon as you know something concrete and again whenever you learn more: "
            "each call adds to the same lead and returns it with what is still unknown. Prospects only."
        ),
        parameters={
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Company or project name, as they gave it."},
                "business_model": {"type": "string", "description": "How they sell: e-commerce, SaaS subscriptions, marketplace/platform, in person, services…"},
                "annual_volume_usd": {"type": "number", "description": "Expected or current payment volume in US dollars per year. Convert what they said; omit if unknown."},
                "timeline": {"type": "string", "description": "When they need to be live or decide, and what is driving it."},
                "needs": {"type": "string", "description": "What they need Stripe for and the pain behind it, in their words where possible."},
                "qualification_notes": {"type": "string", "description": "Who decides, current processor or setup, alternatives they are weighing, anything a colleague should know."},
                "recommended_products": {"type": "array", "items": {"type": "string"}, "description": "The starting set of Stripe products you recommended."},
            },
            "additionalProperties": False,
        },
        run=capture_lead,
        cacheable=False,
    ))
