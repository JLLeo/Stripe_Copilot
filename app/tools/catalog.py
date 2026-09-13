"""
list_products and get_pricing — the catalogue and Stripe's public prices.

`list_products` reads the product catalogue from the seed database.

`get_pricing` reads Public Knowledge only: the `## Price` section of every
knowledge-base document whose header says `Access Level: public`, plus the
three price sections of the pricing overview. Documents marked otherwise are
never opened, so nothing staff-facing can reach the conversation (ADR 0003).
The seed database holds no prices, which is why this tool reads documents
rather than SQL.

When nothing matches, the tool says so. It never guesses a price.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app import database
from app.harness.tools import Tool, ToolContext, ToolRegistry, ToolResult
from app.paths import KNOWLEDGE_BASE_DIR

PRICING_SOURCE = "https://stripe.com/pricing"
# Sections of the pricing overview that hold customer-facing price lines.
OVERVIEW_SECTIONS = ("Standard Pricing", "Key Product Add-on Pricing", "Custom Pricing Options")
CUSTOM_PRICING_NOTE = (
    "Custom pricing (interchange-plus, volume or multi-product discounts, country-specific rates) exists "
    "but is arranged by Stripe's sales team; do not quote custom rates."
)
PRODUCT_FIELDS = ("product_name", "product_group", "short_description")
_STOPWORDS = {"stripe", "for", "the", "and", "pricing", "price", "prices", "cost", "costs", "fee", "fees"}


# ---------------------------------------------------------------------------
# list_products
# ---------------------------------------------------------------------------
def list_products(ctx: ToolContext, args: dict) -> ToolResult:
    group = (args.get("group") or "").strip() or None
    rows = database.list_products(group)
    groups = database.list_product_groups()
    if group and not rows:
        return ToolResult.from_payload({"products": [], "note": f"No product group named {group!r}.", "groups": groups})
    return ToolResult.from_payload({"products": [{k: r.get(k) for k in PRODUCT_FIELDS} for r in rows], "groups": groups})


# ---------------------------------------------------------------------------
# get_pricing
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PriceEntry:
    product: str  # the document's `Product:` header
    title: str  # the document's H1
    lines: tuple[str, ...]
    source: str  # the document's public URL, or its path


def _header(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _section_lines(text: str, heading_pattern: str) -> list[str]:
    """Bullet and plain lines under a heading, up to the next heading of the same or higher level."""
    out: list[str] = []
    capturing = False
    level = 0
    for line in text.splitlines():
        heading = re.match(r"^(#{2,3})\s+(.*)$", line)
        if heading:
            if capturing and len(heading.group(1)) <= level:
                break
            if re.fullmatch(heading_pattern, heading.group(2).strip()):
                capturing, level = True, len(heading.group(1))
                continue
        if capturing and line.strip() and not line.startswith("#"):
            out.append(re.sub(r"^\s*-\s*", "", line).replace("**", "").strip())
    return out


@lru_cache(maxsize=1)
def _price_entries() -> tuple[PriceEntry, ...]:
    """Every public document's price lines, read once."""
    entries: list[PriceEntry] = []
    for path in sorted(KNOWLEDGE_BASE_DIR.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        if _header(text, "Access Level").lower() != "public":
            continue  # structural exclusion: non-public material is never parsed
        lines = _section_lines(text, r"Price")
        if path.name == "pricing_overview.md":
            for section in OVERVIEW_SECTIONS:
                lines += _section_lines(text, re.escape(section))
        if not lines:
            continue
        title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), path.stem)
        entries.append(PriceEntry(
            product=_header(text, "Product") or path.stem,
            title=title,
            lines=tuple(dict.fromkeys(lines)),  # de-duplicate, keep order
            source=_header(text, "Source URL") or str(path.relative_to(KNOWLEDGE_BASE_DIR.parent)),
        ))
    return tuple(entries)


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+]+", text.lower()) if w not in _STOPWORDS}


def get_pricing(ctx: ToolContext, args: dict) -> ToolResult:
    product = (args.get("product") or "").strip()
    wanted = _tokens(product)
    entries = _price_entries()

    # Documents about the product itself first; then any public price line that names it.
    by_document = [e for e in entries if wanted & (_tokens(e.product) | _tokens(e.title))]
    matched = by_document or [
        PriceEntry(e.product, e.title, tuple(l for l in e.lines if wanted & _tokens(l)), e.source)
        for e in entries
        if any(wanted & _tokens(l) for l in e.lines)
    ]
    lines = list(dict.fromkeys(l for e in matched for l in e.lines))
    sources = list(dict.fromkeys(e.source for e in matched))

    if not lines:
        return ToolResult.from_payload({
            "product": product,
            "pricing": [],
            "note": (
                f"No public list price for {product!r} in the material available to me. Do not quote a price; "
                "tell the customer you will confirm it, or point them to stripe.com/pricing. " + CUSTOM_PRICING_NOTE
            ),
            "source": PRICING_SOURCE,
        })
    return ToolResult.from_payload({
        "product": product,
        "pricing": lines,
        "note": "Public list prices; standard card processing applies on top of add-ons. " + CUSTOM_PRICING_NOTE,
        "sources": sources,
    })


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def register(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="list_products",
        description=(
            "Stripe's product catalogue: every product's name, group, and one-line description. "
            "Optionally filter by product group "
            "(Payments, Revenue, Platforms and marketplaces, Money Management, More)."
        ),
        parameters={
            "type": "object",
            "properties": {"group": {"type": "string", "description": "Product group to filter by; omit for all products."}},
            "additionalProperties": False,
        },
        run=list_products,
    ))
    registry.register(Tool(
        name="get_pricing",
        description=(
            "Stripe's public list prices for a product or payment method (e.g. 'Radar', 'Billing', 'Terminal', "
            "'ACH', 'international cards'). Use it for any question about what something costs; never guess a price. "
            "If it returns no lines, say you will confirm rather than estimating."
        ),
        parameters={
            "type": "object",
            "properties": {"product": {"type": "string", "description": "Product or payment method name."}},
            "required": ["product"],
            "additionalProperties": False,
        },
        run=get_pricing,
    ))
