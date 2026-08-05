"""
Milvus Loader
==============
Chunks knowledge_base/*.md files, enriches each chunk with KG metadata,
generates embeddings, and stores everything in Milvus.

Usage:
    python -m app.milvus_loader          # load all files
    python -m app.milvus_loader --force  # drop collection and rebuild
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    MilvusClient,
    connections,
)

# ---------------------------------------------------------------------------
# Ensure app/ package is importable when run as script
# ---------------------------------------------------------------------------
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

load_dotenv(_project_root / ".env")

from app.kg_builder import KnowledgeGraph, get_knowledge_graph  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
KNOWLEDGE_BASE_DIR = _project_root / "knowledge_base"
MILVUS_DB_PATH = str(_project_root / "milvus.db")
COLLECTION_NAME = "stripe_sales_knowledge"
EMBEDDING_DIM = 1536  # text-embedding-3-small
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80

# ======================================================================
# Schema definition
# ======================================================================

SCHEMA_FIELDS = [
    FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
    FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
    # --- metadata (for scalar filtering) ---
    FieldSchema(name="product", dtype=DataType.VARCHAR, max_length=128),
    FieldSchema(name="product_line", dtype=DataType.VARCHAR, max_length=64),
    FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=128),
    FieldSchema(name="source_file", dtype=DataType.VARCHAR, max_length=512),
    FieldSchema(name="source_url", dtype=DataType.VARCHAR, max_length=1024),
    FieldSchema(name="source_type", dtype=DataType.VARCHAR, max_length=32),
    FieldSchema(name="access_level", dtype=DataType.VARCHAR, max_length=32),
    FieldSchema(name="sales_scenario", dtype=DataType.VARCHAR, max_length=256),
    FieldSchema(name="topic", dtype=DataType.VARCHAR, max_length=256),
    FieldSchema(name="chunk_index", dtype=DataType.INT64),
    # --- KG-enriched fields ---
    FieldSchema(name="related_products", dtype=DataType.VARCHAR, max_length=1024),
    FieldSchema(name="supports_methods", dtype=DataType.VARCHAR, max_length=1024),
    FieldSchema(name="complies_with", dtype=DataType.VARCHAR, max_length=512),
    FieldSchema(name="kg_scenarios", dtype=DataType.VARCHAR, max_length=1024),
]

# ---------------------------------------------------------------------------
# Metadata parser (frontmatter in each .md)
# ---------------------------------------------------------------------------
_META_RE = re.compile(r"^([A-Za-z _]+?):\s*(.+)$")


def _parse_frontmatter(text: str) -> dict:
    """Extract key:value metadata from the top of a .md file."""
    meta: dict[str, str] = {}
    lines = text.strip().split("\n")
    in_frontmatter = False
    for line in lines:
        line = line.strip()
        # Skip blank lines, but keep going
        if not line:
            continue
        # Stop only when we've started parsing frontmatter and then hit a heading or list
        if line.startswith("#"):
            if in_frontmatter:
                break
            continue  # Skip the title heading
        if in_frontmatter and (line.startswith("-") or line.startswith("**")):
            break
        m = _META_RE.match(line)
        if m:
            key = m.group(1).strip().lower().replace(" ", "_")
            meta[key] = m.group(2).strip()
            in_frontmatter = True
        elif in_frontmatter:
            break  # Non-matching line after metadata started → end of frontmatter
    return meta


def _extract_product_id(meta: dict, kg: KnowledgeGraph) -> str | None:
    """Map doc metadata -> KG product node id."""
    product_name = meta.get("product", "").lower().replace(" ", "_")
    # Direct match in KG
    node = kg.get_node(product_name)
    if node and node.get("entity_type") == "product":
        return product_name
    # Alias mapping
    aliases = {
        "payments": "payments",
        "checkout": "checkout",
        "payment_links": "payment_links",
        "elements": "elements",
        "payment_methods": "payment_methods",
        "terminal": "terminal",
        "radar": "radar",
        "link": "link",
        "connect": "connect",
        "billing": "billing",
        "subscriptions": "subscriptions",
        "invoicing": "invoicing",
        "tax": "tax",
        "revenue_recognition": "revenue_recognition",
        "sigma": "sigma",
        "data_pipeline": "data_pipeline",
        "pricing": "payments",        # Pricing docs → Payments product
        "security": "payments",       # Security docs → Payments product
        "sales_playbook": "payments", # Sales playbook → Payments product
        "custom_pricing_policy": "payments",
        "mock_security_policy": "payments",
    }
    return aliases.get(product_name)


# ---------------------------------------------------------------------------
# Document loader
# ---------------------------------------------------------------------------
def load_markdown_documents(kg: KnowledgeGraph) -> list[Document]:
    """Walk knowledge_base/ and return langchain Documents with KG-enriched metadata."""
    documents: list[Document] = []

    for file_path in sorted(KNOWLEDGE_BASE_DIR.rglob("*.md")):
        # skip non-content files
        if file_path.name.endswith("knowledge_graph.yaml"):
            continue

        text = file_path.read_text(encoding="utf-8")
        if not text.strip():
            continue

        # Parse frontmatter
        meta = _parse_frontmatter(text)

        # Remove frontmatter from body (everything after first ## heading)
        body_match = re.search(r"\n##\s", text)
        body = text[body_match.start():].strip() if body_match else text

        # Determine product id
        product_id = _extract_product_id(meta, kg)

        # Build base metadata — use KG product_id (lowercase) as the canonical product field
        doc_meta = {
            "doc_id": meta.get("doc_id", file_path.stem),
            "product": product_id or meta.get("product", "unknown").lower().replace(" ", "_"),
            "product_line": meta.get("product_line", ""),
            "source_file": str(file_path.relative_to(_project_root)),
            "source_url": meta.get("source_url", ""),
            "source_type": meta.get("source_type", "public_doc"),
            "access_level": meta.get("access_level", "public"),
            "sales_scenario": meta.get("sales_scenario", ""),
            "topic": meta.get("topic", file_path.stem),
            # KG-enriched fields (comma-joined for Milvus VARCHAR)
            "related_products": "",
            "supports_methods": "",
            "complies_with": "",
            "kg_scenarios": "",
        }

        # Enrich with KG
        if product_id:
            related = kg.get_related_products(product_id, radius=1)
            doc_meta["related_products"] = ",".join(related)
            doc_meta["supports_methods"] = ",".join(kg.get_payment_methods(product_id))
            doc_meta["complies_with"] = ",".join(kg.get_compliance_standards(product_id))

        documents.append(Document(page_content=body, metadata=doc_meta))

    return documents


# ---------------------------------------------------------------------------
# Milvus collection management
# ---------------------------------------------------------------------------
def create_collection(client: MilvusClient) -> None:
    """Create the collection if it doesn't exist."""
    if client.has_collection(COLLECTION_NAME):
        return

    schema = CollectionSchema(
        fields=SCHEMA_FIELDS,
        description="Stripe Sales Copilot Knowledge Base — chunks with KG metadata",
        enable_dynamic_field=False,
    )

    # Build index params — only vector index; Milvus auto-indexes scalars
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="embedding",
        index_type="AUTOINDEX",
        metric_type="COSINE",
    )

    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
    )
    print(f"[Milvus] Collection '{COLLECTION_NAME}' created.")


def drop_collection(client: MilvusClient) -> None:
    """Drop the collection if it exists."""
    if client.has_collection(COLLECTION_NAME):
        client.drop_collection(COLLECTION_NAME)
        print(f"[Milvus] Collection '{COLLECTION_NAME}' dropped.")


# ---------------------------------------------------------------------------
# Main ingestion pipeline
# ---------------------------------------------------------------------------
def ingest(force_rebuild: bool = False) -> dict:
    """
    Full ingestion pipeline:
      1. Load KG
      2. Load markdown docs + parse frontmatter
      3. Chunk
      4. Enrich chunk metadata with KG
      5. Generate embeddings
      6. Insert into Milvus
    """
    print("=" * 60)
    print("Stripe Sales Copilot — Knowledge Base → Milvus Ingestion")
    print("=" * 60)

    # 1. Load KG
    print("\n[1/6] Loading knowledge graph...")
    kg = get_knowledge_graph()
    kg_summary = kg.summary()
    print(f"       {kg_summary['total_nodes']} nodes, {kg_summary['total_edges']} edges loaded.")

    # 2. Load markdown documents
    print("[2/6] Loading markdown documents...")
    raw_docs = load_markdown_documents(kg)
    print(f"       {len(raw_docs)} documents loaded.")

    # 3. Chunk
    print(f"[3/6] Chunking (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n## ", "\n### ", "\n- ", "\n", ". ", " ", ""],
    )
    chunks = text_splitter.split_documents(raw_docs)

    # Transfer doc-level metadata to each chunk + add chunk_index
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = i

    print(f"       {len(chunks)} chunks created.")

    # 4. Prepare for embedding
    print("[4/6] Generating embeddings (text-embedding-3-small)...")
    texts = [c.page_content for c in chunks]
    embeddings_model = OpenAIEmbeddings(model="text-embedding-3-small")
    vectors = embeddings_model.embed_documents(texts)
    print(f"       {len(vectors)} vectors generated (dim={len(vectors[0])}).")

    # 5. Connect to Milvus
    print(f"[5/6] Connecting to Milvus Lite → {MILVUS_DB_PATH}")
    client = MilvusClient(uri=MILVUS_DB_PATH)

    if force_rebuild:
        drop_collection(client)
    create_collection(client)

    # 6. Insert
    print(f"[6/6] Inserting {len(chunks)} chunks into Milvus...")
    rows = []
    for chunk, vector in zip(chunks, vectors):
        meta = chunk.metadata
        rows.append({
            "id": str(uuid4()),
            "text": chunk.page_content,
            "embedding": vector,
            "product": meta.get("product", ""),
            "product_line": meta.get("product_line", ""),
            "doc_id": meta.get("doc_id", ""),
            "source_file": meta.get("source_file", ""),
            "source_url": meta.get("source_url", ""),
            "source_type": meta.get("source_type", ""),
            "access_level": meta.get("access_level", ""),
            "sales_scenario": meta.get("sales_scenario", ""),
            "topic": meta.get("topic", ""),
            "chunk_index": meta.get("chunk_index", 0),
            "related_products": meta.get("related_products", ""),
            "supports_methods": meta.get("supports_methods", ""),
            "complies_with": meta.get("complies_with", ""),
            "kg_scenarios": meta.get("kg_scenarios", ""),
        })

    # Batch insert
    batch_size = 100
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        client.insert(collection_name=COLLECTION_NAME, data=batch)
        print(f"       Inserted {start + len(batch)}/{len(rows)}...")

    # Verify & load
    client.load_collection(COLLECTION_NAME)
    stats = client.get_collection_stats(COLLECTION_NAME)
    print(f"\n[OK] Ingestion complete.")
    print(f"   Collection: {COLLECTION_NAME}")
    print(f"   Row count: {stats['row_count']}")
    print(f"   Milvus DB:  {MILVUS_DB_PATH}")

    return {"documents": len(raw_docs), "chunks": len(chunks), "rows": stats["row_count"]}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load Stripe KB into Milvus")
    parser.add_argument("--force", action="store_true", help="Drop collection & rebuild")
    args = parser.parse_args()

    ingest(force_rebuild=args.force)
