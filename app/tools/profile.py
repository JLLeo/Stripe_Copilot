"""
get_my_profile — the Customer Profile of the customer the agent is talking to.

The tool takes no arguments: it reads the customer the session is bound to, so
there is no parameter through which another customer's data could be requested.
"""

from __future__ import annotations

from app import database
from app.database import CUSTOMER_PROFILE_FIELDS
from app.harness.tools import Tool, ToolContext, ToolRegistry, ToolResult

PROFILE_FIELDS = ("customer_id", "customer_name", *CUSTOMER_PROFILE_FIELDS)
USAGE_FIELDS = ("product_name", "product_group", "usage_status", "start_date", "monthly_volume", "adoption_level", "notes")


def get_my_profile(ctx: ToolContext, args: dict) -> ToolResult:
    if not ctx.customer_id:
        return ToolResult.from_payload({
            "profile": None,
            "products_in_use": [],
            "note": "This is a new prospect with no Stripe account; nothing is on file. Ask about their business.",
        })
    profile = database.get_customer(ctx.customer_id) or {}
    usage = database.get_customer_product_usage(ctx.customer_id)
    return ToolResult.from_payload({
        "profile": {k: profile.get(k) for k in PROFILE_FIELDS},
        "products_in_use": [{k: row.get(k) for k in USAGE_FIELDS} for row in usage],
    })


def register(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="get_my_profile",
        description=(
            "What Stripe already knows about the customer you are talking to: company, stage, industry, "
            "business model, payment volume, pain points, and the Stripe products they use today. "
            "Takes no arguments. Call it before recommending anything so the advice fits their situation."
        ),
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        run=get_my_profile,
    ))
