"""
search_knowledge — hybrid, graph-expanded search over Public Knowledge.

The model links the question to the graph's vocabulary by naming products and
topics (Entity Linking); the graph widens the search one hop (Graph
Expansion); dense and BM25 legs run with the same filter and are fused. The
result carries the passages and their sources; the `source_extraction`
guardrail lifts the sources into the turn so the reply can cite them.
"""

from __future__ import annotations

from app.harness.hooks import HookEvent, HookRegistry, ToolUseContext
from app.harness.tools import Tool, ToolContext, ToolRegistry, ToolResult
from app.retrieval import linking
from app.retrieval.index import EmbeddingDimensionMismatch, IndexNotBuilt, KnowledgeIndex

TOP_K = 6


def make_search_knowledge(index: KnowledgeIndex):
    def search_knowledge(ctx: ToolContext, args: dict) -> ToolResult:
        question = (args.get("question") or "").strip()
        if not question:
            return ToolResult.error("search_knowledge needs a question.")
        try:
            response = index.search(
                question,
                products=list(args.get("products") or []),
                topics=list(args.get("topics") or []),
                top_k=TOP_K,
            )
        except (IndexNotBuilt, EmbeddingDimensionMismatch) as exc:
            return ToolResult.error(str(exc))
        return ToolResult.from_payload(
            {
                "question": question,
                "linked": {
                    "products": response.linked.products,
                    "topics": response.linked.topics,
                    "expanded_products": response.linked.expanded_products,
                    "by_keyword_fallback": response.linked.fallback,
                },
                "results": [
                    {"product": h.product, "source": h.title, "section": h.heading, "url": h.source_url, "text": h.text}
                    for h in response.hits
                ],
                "sources": response.sources,
                "note": (
                    "Public documentation only. Cite the source when you use a passage; "
                    "say so if nothing here answers the question."
                ),
            },
            sources=response.sources,
        )

    return search_knowledge


def register(registry: ToolRegistry, index: KnowledgeIndex) -> None:
    vocab = linking.vocabulary(index.kg)

    def describe(ids) -> str:
        return "; ".join(f"{i} = {vocab.labels[i]}" for i in ids)

    registry.register(Tool(
        name="search_knowledge",
        description=(
            "Search Stripe's public product documentation for one specific question. Name the products and "
            "topics it is about so the knowledge graph can widen the search to related products; leave them "
            "empty only if the question names nothing specific. Returns the best passages with their sources — "
            "cite them. Use this first; if the question spans several products, asks for a comparison, or the "
            "passages come back thin, hand it to research instead of searching again and again."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to search for, in the customer's words or your paraphrase.",
                },
                "products": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(vocab.products)},
                    "description": "Products the question is about: " + describe(vocab.products),
                },
                "topics": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(vocab.topics)},
                    "description": (
                        "Compliance standards, payment methods, regions or customer sizes involved: " + describe(vocab.topics)
                    ),
                },
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        run=make_search_knowledge(index),
    ))


# ---------------------------------------------------------------------------
# source_extraction — PostToolUse
# ---------------------------------------------------------------------------
def source_extraction(ctx: ToolUseContext, result: ToolResult) -> None:
    """Collect the sources a tool cited into the turn, de-duplicated, for the reply to carry."""
    for source in result.meta.get("sources") or ():
        if source not in ctx.turn.sources:
            ctx.turn.sources.append(source)
    return None


def register_guardrails(hooks: HookRegistry) -> None:
    hooks.register(HookEvent.POST_TOOL_USE, source_extraction)
