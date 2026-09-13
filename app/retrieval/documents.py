"""
Public Knowledge documents and their metadata.

Every `knowledge_base/**/*.md` carries a header block (`Product:`, `Access
Level:`, `Source URL:` …). Only documents whose access level is `public`
are loaded; anything else is Internal Knowledge — its header is checked and
nothing of it is parsed, chunked or embedded (ADR 0003). This is the one
place that applies that rule; every reader of the knowledge base goes
through it. Each document is mapped to a knowledge-graph product so its
chunks can be filtered by product and enriched with graph neighbours.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.retrieval.graph import KnowledgeGraph

PUBLIC = "public"
# Documents whose `Product:` header is not a graph node are filed under the product they describe.
HEADER_PRODUCT_MAP = {"pricing": "payments", "security": "payments"}


@dataclass(frozen=True)
class SourceDocument:
    doc_id: str  # file stem
    title: str  # H1
    product: str  # knowledge-graph product id
    product_line: str
    topic: str
    source_url: str
    access_level: str
    path: Path
    body: str  # full markdown (the chunker strips the header block)
    related_products: tuple[str, ...] = field(default_factory=tuple)
    supports_methods: tuple[str, ...] = field(default_factory=tuple)
    complies_with: tuple[str, ...] = field(default_factory=tuple)


def header(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def access_level(text: str) -> str:
    return header(text, "Access Level").lower() or "unknown"


def product_id(text: str, kg: KnowledgeGraph) -> str:
    raw = header(text, "Product").lower().replace("stripe ", "").strip().replace(" ", "_")
    if kg.type_of(raw) == "product":
        return raw
    return HEADER_PRODUCT_MAP.get(raw, raw or "unknown")


def load_public_documents(knowledge_base: Path, kg: KnowledgeGraph) -> list[SourceDocument]:
    """Every public markdown document under the knowledge base, sorted by path."""
    docs: list[SourceDocument] = []
    for path in sorted(knowledge_base.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        if access_level(text) != PUBLIC:
            continue
        product = product_id(text, kg)
        title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), path.stem)
        docs.append(SourceDocument(
            doc_id=path.stem,
            title=title,
            product=product,
            product_line=header(text, "Product Line"),
            topic=header(text, "Topic"),
            source_url=header(text, "Source URL"),
            access_level=PUBLIC,
            path=path,
            body=text,
            related_products=tuple(kg.related_products(product)),
            supports_methods=tuple(kg.targets(product, "supports_method")),
            complies_with=tuple(kg.targets(product, "complies_with")),
        ))
    return docs
