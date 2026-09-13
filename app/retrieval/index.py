"""
The knowledge index — dense and BM25 legs over identical public chunks.

Two Milvus Lite collections hold the same chunks and metadata: `knowledge_dense`
with the embedding vector and `knowledge_sparse` with a BM25 sparse vector that
Milvus computes from the text. Milvus Lite on Windows cannot hold two vector
indexes in one collection, so they live side by side and fusion happens here,
by reciprocal rank (ADR 0004). Both legs take the same scalar filter, so the
knowledge-graph expansion constrains dense and lexical retrieval alike.

Embeddings come from the Provider seam — the same adapter the harness talks
to — so tests build a real index from a fake embedder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence, TypedDict

from pymilvus import CollectionSchema, DataType, Function, FunctionType, MilvusClient

from app.harness.provider import Provider
from app.paths import KNOWLEDGE_BASE_DIR, PROJECT_ROOT
from app.retrieval import chunking, linking
from app.retrieval.documents import SourceDocument, load_public_documents
from app.retrieval.graph import KnowledgeGraph

DEFAULT_MILVUS_URI = str(PROJECT_ROOT / "milvus.db")
DENSE = "knowledge_dense"
SPARSE = "knowledge_sparse"
RRF_K = 60
EMBED_BATCH = 64
DEFAULT_EMBEDDING_DIM = 1536  # text-embedding-3-small; used only when there is nothing to index

METADATA_FIELDS = ("product", "product_line", "doc_id", "title", "heading", "source_url", "access_level",
                   "related_products", "supports_methods", "complies_with", "chunk_index")
OUTPUT_FIELDS = ("id", "text", "product", "doc_id", "title", "heading", "source_url", "access_level")


class IndexNotBuilt(RuntimeError):
    """The knowledge collections do not exist at this Milvus URI."""


class EmbeddingDimensionMismatch(RuntimeError):
    """The provider's vectors are not the size the index was built with."""


class Source(TypedDict):
    title: str
    url: str


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    text: str
    product: str
    doc_id: str
    title: str
    heading: str
    source_url: str
    dense_rank: int | None
    sparse_rank: int | None
    score: float  # reciprocal-rank fusion score

    @classmethod
    def from_entity(cls, entity: dict[str, Any], dense_rank: int | None, sparse_rank: int | None, score: float) -> "Hit":
        return cls(
            chunk_id=entity["id"], text=entity["text"], product=entity["product"], doc_id=entity["doc_id"],
            title=entity["title"], heading=entity["heading"], source_url=entity["source_url"],
            dense_rank=dense_rank, sparse_rank=sparse_rank, score=score,
        )


@dataclass
class SearchResponse:
    question: str
    linked: linking.Linked
    filter_expr: str
    hits: list[Hit] = field(default_factory=list)

    @property
    def sources(self) -> list[Source]:
        seen: dict[tuple[str, str], None] = {}
        for h in self.hits:
            seen.setdefault((h.title, h.source_url), None)
        return [Source(title=t, url=u) for t, u in seen]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
def _add_metadata(schema: CollectionSchema) -> None:
    for name in METADATA_FIELDS:
        if name == "chunk_index":
            schema.add_field(name, DataType.INT64)
        else:
            schema.add_field(name, DataType.VARCHAR, max_length=1024)


def _create_collections(client: MilvusClient, dim: int) -> None:
    dense = client.create_schema(auto_id=False, enable_dynamic_field=False)
    dense.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
    dense.add_field("text", DataType.VARCHAR, max_length=8192)
    dense.add_field("embedding", DataType.FLOAT_VECTOR, dim=dim)
    _add_metadata(dense)
    dense_index = client.prepare_index_params()
    dense_index.add_index(field_name="embedding", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(DENSE, schema=dense, index_params=dense_index)

    sparse = client.create_schema(auto_id=False, enable_dynamic_field=False)
    sparse.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
    sparse.add_field("text", DataType.VARCHAR, max_length=8192, enable_analyzer=True)
    sparse.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
    sparse.add_function(Function(
        name="bm25", function_type=FunctionType.BM25, input_field_names=["text"], output_field_names=["sparse"],
    ))
    _add_metadata(sparse)
    sparse_index = client.prepare_index_params()
    sparse_index.add_index(field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
    client.create_collection(SPARSE, schema=sparse, index_params=sparse_index)


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
def build_index(
    provider: Provider,
    knowledge_base: Path = KNOWLEDGE_BASE_DIR,
    milvus_uri: str = DEFAULT_MILVUS_URI,
    rebuild: bool = False,
    kg: KnowledgeGraph | None = None,
    max_chars: int = chunking.DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """Index every public document into both collections. Returns counts."""
    kg = kg or KnowledgeGraph()
    documents = load_public_documents(knowledge_base, kg)
    rows = _rows(documents, max_chars)

    vectors: list[list[float]] = []
    for start in range(0, len(rows), EMBED_BATCH):
        vectors.extend(provider.embed([r["text"] for r in rows[start:start + EMBED_BATCH]]))

    client = MilvusClient(uri=milvus_uri)
    try:
        if rebuild:
            for name in client.list_collections():
                client.drop_collection(name)  # older layouts included one collection with internal chunks
        if not client.has_collection(DENSE) or not client.has_collection(SPARSE):
            _create_collections(client, dim=len(vectors[0]) if vectors else DEFAULT_EMBEDDING_DIM)
        for start in range(0, len(rows), 100):
            batch = rows[start:start + 100]
            # upsert: re-indexing a changed document replaces its chunks by id instead of duplicating them
            client.upsert(DENSE, [{**r, "embedding": v} for r, v in zip(batch, vectors[start:start + 100])])
            client.upsert(SPARSE, batch)
        client.load_collection(DENSE)
        client.load_collection(SPARSE)
    finally:
        client.close()
    return {"documents": len(documents), "chunks": len(rows), "collections": [DENSE, SPARSE]}


def _rows(documents: Sequence[SourceDocument], max_chars: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for doc in documents:
        for chunk in chunking.chunk_markdown(doc.body, title=doc.title, max_chars=max_chars):
            rows.append({
                "id": f"{doc.doc_id}#{chunk.index:03d}",
                "text": chunk.text,
                "product": doc.product,
                "product_line": doc.product_line,
                "doc_id": doc.doc_id,
                "title": doc.title,
                "heading": chunk.heading,
                "source_url": doc.source_url,
                "access_level": doc.access_level,
                "related_products": ",".join(doc.related_products),
                "supports_methods": ",".join(doc.supports_methods),
                "complies_with": ",".join(doc.complies_with),
                "chunk_index": chunk.index,
            })
    return rows


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
class KnowledgeIndex:
    def __init__(self, provider: Provider, milvus_uri: str = DEFAULT_MILVUS_URI, kg: KnowledgeGraph | None = None):
        self.provider = provider
        self.milvus_uri = milvus_uri
        self.kg = kg or KnowledgeGraph()
        self._client: MilvusClient | None = None
        self._dim: int | None = None

    @property
    def client(self) -> MilvusClient:
        if self._client is None:
            client = MilvusClient(uri=self.milvus_uri)
            if not (client.has_collection(DENSE) and client.has_collection(SPARSE)):
                client.close()
                raise IndexNotBuilt(f"knowledge index not built at {self.milvus_uri}; run: python -m app.retrieval.ingest")
            client.load_collection(DENSE)
            client.load_collection(SPARSE)
            self._client = client
            self._dim = next(
                f["params"]["dim"] for f in client.describe_collection(DENSE)["fields"] if f["name"] == "embedding"
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def search(self, question: str, products: list[str], topics: list[str], top_k: int = 6) -> SearchResponse:
        linked = linking.link(self.kg, question, products, topics)
        expr = linking.filter_expr(linked)
        candidates = top_k * 3

        vector = self.provider.embed([question])[0]
        if self._dim is not None and len(vector) != self._dim:
            raise EmbeddingDimensionMismatch(
                f"provider embeds {len(vector)} dimensions but the index at {self.milvus_uri} was built with {self._dim}; "
                "rebuild it with: python -m app.retrieval.ingest"
            )
        dense_hits = self.client.search(
            DENSE, data=[vector], anns_field="embedding",
            limit=candidates, filter=expr, output_fields=list(OUTPUT_FIELDS),
        )[0]
        sparse_hits = self.client.search(
            SPARSE, data=[question], anns_field="sparse",
            limit=candidates, filter=expr, output_fields=list(OUTPUT_FIELDS),
        )[0] if question.strip() else []

        fused: dict[str, dict[str, Any]] = {}
        for leg, hits in (("dense", dense_hits), ("sparse", sparse_hits)):
            for rank, hit in enumerate(hits, start=1):
                entity = hit["entity"]
                slot = fused.setdefault(entity["id"], {"entity": entity, "dense": None, "sparse": None, "score": 0.0})
                slot[leg] = rank
                slot["score"] += 1.0 / (RRF_K + rank)

        ordered = sorted(fused.values(), key=lambda s: (-s["score"], s["entity"]["id"]))[:top_k]
        return SearchResponse(
            question=question, linked=linked, filter_expr=expr,
            hits=[Hit.from_entity(s["entity"], s["dense"], s["sparse"], s["score"]) for s in ordered],
        )

    def dump(self, kind: str, limit: int = 2000) -> list[dict[str, Any]]:
        """Up to `limit` rows of one leg — for tests and inspection, not for production reads."""
        name = DENSE if kind == "dense" else SPARSE
        return self.client.query(name, filter='id != ""', output_fields=list(OUTPUT_FIELDS), limit=limit)
