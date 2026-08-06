"""
Quick test: query Milvus directly and inspect retrieved chunks.

Usage:
    python test_milvus.py
"""

from pymilvus import MilvusClient
from langchain_openai import OpenAIEmbeddings

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MILVUS_DB = "milvus.db"
COLLECTION = "stripe_sales_knowledge"

# ---------------------------------------------------------------------------
# 1. Connect
# ---------------------------------------------------------------------------
client = MilvusClient(uri=MILVUS_DB)
client.load_collection(COLLECTION)

# ---------------------------------------------------------------------------
# 2. Embed the test query
# ---------------------------------------------------------------------------
test_query = (
    "A marketplace customer needs seller onboarding and payouts. "
    "Which Stripe product should I recommend?"
)

embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
query_vec = embeddings.embed_query(test_query)

# ---------------------------------------------------------------------------
# 3. Search
# ---------------------------------------------------------------------------
results = client.search(
    collection_name=COLLECTION,
    data=[query_vec],
    limit=3,
    output_fields=[
        "text", "product", "product_line", "doc_id",
        "source_file", "source_url", "source_type", "access_level",
        "sales_scenario", "topic", "related_products", "supports_methods",
    ],
)

# ---------------------------------------------------------------------------
# 4. Display
# ---------------------------------------------------------------------------
print("\nTest query:")
print(f"  {test_query}")

print("\nTop retrieved chunks:")
for i, hit in enumerate(results[0]):
    entity = hit.get("entity", {})
    score = hit.get("distance", 0.0)
    print("-" * 80)
    print(f"[{i+1}] Score:        {score:.4f}")
    print(f"    Product:      {entity.get('product', 'N/A')}")
    print(f"    Product Line: {entity.get('product_line', 'N/A')}")
    print(f"    Topic:        {entity.get('topic', 'N/A')}")
    print(f"    Source file:  {entity.get('source_file', 'N/A')}")
    print(f"    Source URL:   {entity.get('source_url', 'N/A')}")
    print(f"    Access:       {entity.get('access_level', 'N/A')}")
    print(f"    Scenario:     {entity.get('sales_scenario', 'N/A')}")
    print(f"    Related:      {entity.get('related_products', 'N/A')}")
    print(f"    Methods:      {entity.get('supports_methods', 'N/A')}")
    text = entity.get("text", "")
    print(f"    --- Text ---")
    print(f"    {text[:500]}")
