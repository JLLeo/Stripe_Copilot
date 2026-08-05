"""
Milvus Retriever — KG-Enhanced Hybrid Retrieval
=================================================
Query pipeline:
  1. Accept raw user query
  2. Expand via KG → product filter expression
  3. Embed query
  4. Search Milvus with vector similarity + optional scalar filter
  5. Return ranked, source-grounded results
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from pymilvus import MilvusClient

# ---------------------------------------------------------------------------
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

load_dotenv(_project_root / ".env")

from app.kg_retriever import KGRetriever, QueryExpansion, get_kg_retriever  # noqa: E402

# ---------------------------------------------------------------------------
COLLECTION_NAME = "stripe_sales_knowledge"
MILVUS_DB_PATH = str(_project_root / "milvus.db")
EMBEDDING_MODEL = "text-embedding-3-small"

# Field set to return from Milvus
OUTPUT_FIELDS = [
    "id", "text", "product", "product_line", "doc_id",
    "source_file", "source_url", "source_type", "access_level",
    "sales_scenario", "topic", "related_products", "supports_methods",
]


@dataclass
class RetrievalResult:
    """A single retrieved chunk with metadata."""
    chunk_id: str
    text: str
    score: float
    product: str
    product_line: str
    doc_id: str
    source_file: str
    source_url: str
    source_type: str
    access_level: str
    sales_scenario: str
    topic: str
    related_products: list[str] = field(default_factory=list)
    supports_methods: list[str] = field(default_factory=list)


@dataclass
class RetrievalResponse:
    """Full response from the retrieval pipeline."""
    query: str
    expansion: QueryExpansion
    results: list[RetrievalResult] = field(default_factory=list)
    search_mode: str = "vector"          # "vector" | "kg_filtered"
    elapsed_ms: float = 0.0

    @property
    def top_k_chunks(self) -> list[str]:
        """Return just the text of top chunks (for LLM prompt assembly)."""
        return [r.text for r in self.results[:5]]

    @property
    def sources(self) -> list[str]:
        """Deduplicated source file paths."""
        return list(dict.fromkeys(r.source_file for r in self.results))


class MilvusRetriever:
    """Hybrid retriever: KG expansion + vector search on Milvus."""

    def __init__(
        self,
        kg_retriever: KGRetriever | None = None,
        milvus_uri: str | None = None,
    ):
        self.kg_retriever = kg_retriever or get_kg_retriever()
        self.milvus_uri = milvus_uri or MILVUS_DB_PATH
        self.embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
        self._client: MilvusClient | None = None

    @property
    def client(self) -> MilvusClient:
        if self._client is None:
            self._client = MilvusClient(uri=self.milvus_uri)
            # Load collection into memory (required before search)
            self._client.load_collection(COLLECTION_NAME)
        return self._client

    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        top_k: int = 5,
        use_kg_filter: bool = True,
        access_level: str | None = None,
    ) -> RetrievalResponse:
        """
        Main entry point: expand query with KG, embed, search Milvus.

        Parameters
        ----------
        query : str
            Raw user question.
        top_k : int
            Number of results to return.
        use_kg_filter : bool
            If True, use KG expansion to build a Milvus filter expr.
            If False, pure vector search (no metadata filter).
        access_level : str | None
            If "public", exclude internal_mock chunks.
        """
        import time
        t0 = time.time()

        # 1. KG expansion
        expansion = self.kg_retriever.expand(query)
        filter_expr = None
        search_mode = "vector"

        if use_kg_filter:
            kg_filter = self.kg_retriever.build_filter_expr(expansion)
            filters = []
            if kg_filter:
                filters.append(kg_filter)
                search_mode = "kg_filtered"
            if access_level == "public":
                filters.append('access_level == "public"')
            if filters:
                filter_expr = " and ".join(filters)

        # 2. Embed query
        query_vec = self.embeddings.embed_query(query)

        # 3. Search Milvus
        raw_results = self.client.search(
            collection_name=COLLECTION_NAME,
            data=[query_vec],
            limit=top_k,
            output_fields=OUTPUT_FIELDS,
            filter=filter_expr,
        )

        # 4. Parse results
        results: list[RetrievalResult] = []
        for hit in raw_results[0]:
            entity = hit.get("entity", {})
            results.append(RetrievalResult(
                chunk_id=entity.get("id", ""),
                text=entity.get("text", ""),
                score=hit.get("distance", 0.0),
                product=entity.get("product", ""),
                product_line=entity.get("product_line", ""),
                doc_id=entity.get("doc_id", ""),
                source_file=entity.get("source_file", ""),
                source_url=entity.get("source_url", ""),
                source_type=entity.get("source_type", ""),
                access_level=entity.get("access_level", ""),
                sales_scenario=entity.get("sales_scenario", ""),
                topic=entity.get("topic", ""),
                related_products=_split_csv(entity.get("related_products", "")),
                supports_methods=_split_csv(entity.get("supports_methods", "")),
            ))

        elapsed = (time.time() - t0) * 1000

        return RetrievalResponse(
            query=query,
            expansion=expansion,
            results=results,
            search_mode=search_mode,
            elapsed_ms=elapsed,
        )

    # ------------------------------------------------------------------
    def search_public_only(self, query: str, top_k: int = 5) -> RetrievalResponse:
        """Shortcut: search only public knowledge (exclude internal_mock)."""
        return self.search(query, top_k=top_k, use_kg_filter=True, access_level="public")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _split_csv(value: str) -> list[str]:
    """Split a comma-separated string into a list, filtering empties."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_retriever_instance: MilvusRetriever | None = None


def get_milvus_retriever() -> MilvusRetriever:
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = MilvusRetriever()
    return _retriever_instance


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    retriever = MilvusRetriever()

    test_queries = [
        "Our marketplace needs seller onboarding and payouts to EU banks",
        "SaaS platform with subscription billing in Europe, need VAT handling",
        "How do I prevent fraud on my ecommerce store?",
        "We have $5M annual volume and need custom pricing",
        "I want to sell online without coding — fast setup",
        "What security certifications does Stripe have for enterprise?",
    ]

    for q in test_queries:
        resp = retriever.search(q, top_k=3)
        print(f"\n{'='*70}")
        print(f"[Q] {resp.query}")
        print(f"   Mode: {resp.search_mode} | {resp.elapsed_ms:.0f}ms | {len(resp.results)} results")
        if resp.expansion.matched_products:
            print(f"   Matched products: {resp.expansion.matched_products}")
        if resp.expansion.related_products:
            print(f"   Related (KG):    {resp.expansion.related_products}")
        for i, r in enumerate(resp.results):
            print(f"   [{i+1}] product={r.product} | score={r.score:.3f} | {r.source_file}")
            print(f"       {r.text[:120]}...")
