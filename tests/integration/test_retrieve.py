"""
End-to-end test: KG expansion -> Milvus search -> Agent response.

Run:
    python tests/integration/test_retrieve.py

Or test a custom query:
    python tests/integration/test_retrieve.py "your question here"
"""


import sys as _sys
from pathlib import Path as _Path

# Runnable from anywhere: put the project root on sys.path before importing app.
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))

import sys
import time

# ---------------------------------------------------------------------------
# Test queries
# ---------------------------------------------------------------------------
DEFAULT_QUERIES = [
    "A marketplace customer needs seller onboarding and payouts. Which Stripe product should I recommend?",
    "SaaS platform with subscription billing in Europe, need VAT handling",
    "How do I prevent fraud on my ecommerce store?",
    "We have $5M annual volume and need custom pricing",
    "I want to sell online without coding, fast setup",
]

# ---------------------------------------------------------------------------
# Take custom query from CLI, or use defaults
# ---------------------------------------------------------------------------
if len(sys.argv) > 1:
    queries = [" ".join(sys.argv[1:])]
else:
    queries = DEFAULT_QUERIES

# ---------------------------------------------------------------------------
# Lazy init (same singletons as the real agent)
# ---------------------------------------------------------------------------
from app.kg_builder import get_knowledge_graph
from app.kg_retriever import get_kg_retriever
from app.milvus_retriever import get_milvus_retriever

kg_builder = get_knowledge_graph()
kg = get_kg_retriever()
milvus = get_milvus_retriever()

# ---------------------------------------------------------------------------
# Run each query
# ---------------------------------------------------------------------------
for idx, query in enumerate(queries):
    t_start = time.time()

    print("=" * 80)
    print(f"QUERY {idx+1}: {query}")
    print("=" * 80)

    # ==================================================================
    # Phase 1: KG Expansion
    # ==================================================================
    print("\n" + "-" * 60)
    print("PHASE 1: Knowledge Graph Expansion")
    print("-" * 60)

    expansion = kg.expand(query)

    print(f"  Matched scenarios  ({len(expansion.matched_scenarios)}):")
    for sid in expansion.matched_scenarios:
        node = kg_builder.get_node(sid)
        name = node.get("name", sid) if node else sid
        print(f"    - {sid}  ({name})")

    print(f"\n  Matched products   ({len(expansion.matched_products)}):")
    for pid in expansion.matched_products:
        node = kg_builder.get_node(pid)
        name = node.get("name", pid) if node else pid
        print(f"    - {pid}  ({name})")

    print(f"\n  KG-expanded related products ({len(expansion.related_products)}):")
    for pid in expansion.related_products:
        node = kg_builder.get_node(pid)
        name = node.get("name", pid) if node else pid
        print(f"    - {pid}  ({name})")

    print(f"\n  All products combined ({len(expansion.all_products)}):")
    print(f"    {expansion.all_products}")

    print(f"\n  Matched geographies ({len(expansion.matched_geos)}):")
    for gid in expansion.matched_geos:
        node = kg_builder.get_node(gid)
        name = node.get("name", gid) if node else gid
        print(f"    - {gid}  ({name})")

    if expansion.matched_methods:
        print(f"\n  Matched payment methods ({len(expansion.matched_methods)}):")
        for mid in expansion.matched_methods[:8]:
            node = kg_builder.get_node(mid)
            name = node.get("name", mid) if node else mid
            print(f"    - {mid}  ({name})")
        if len(expansion.matched_methods) > 8:
            print(f"    ... and {len(expansion.matched_methods) - 8} more")

    print(f"\n  Escalation: {expansion.should_escalate} -> {expansion.escalation_team}")
    print(f"  Confidence: {expansion.confidence:.2f}")

    # Show the Milvus filter that KG produced
    filter_expr = kg.build_filter_expr(expansion)
    if filter_expr:
        print(f"\n  Milvus filter expression:")
        print(f"    {filter_expr}")
    else:
        print(f"\n  No filter (pure vector search)")

    # ==================================================================
    # Phase 2: Milvus Retrieval
    # ==================================================================
    print("\n" + "-" * 60)
    print("PHASE 2: Milvus Retrieval")
    print("-" * 60)

    # with KG filter
    resp_filtered = milvus.search(query, top_k=5, use_kg_filter=True, access_level="public")
    print(f"\n  [KG-filtered search]  {len(resp_filtered.results)} results in {resp_filtered.elapsed_ms:.0f}ms")
    for i, r in enumerate(resp_filtered.results):
        print(f"\n  [{i+1}] score={r.score:.4f}  |  product={r.product}  |  {r.source_file}")
        print(f"       access={r.access_level}  |  scenario={r.sales_scenario}")
        if r.related_products:
            print(f"       KG-related: {r.related_products}")
        text_preview = r.text[:200].replace("\n", " ").strip()
        print(f"       text: {text_preview}...")

    # without KG filter (for comparison)
    resp_vector = milvus.search(query, top_k=5, use_kg_filter=False)
    print(f"\n  [Pure vector search]  {len(resp_vector.results)} results in {resp_vector.elapsed_ms:.0f}ms")
    for i, r in enumerate(resp_vector.results):
        print(f"\n  [{i+1}] score={r.score:.4f}  |  product={r.product}  |  {r.source_file}")
        text_preview = r.text[:120].replace("\n", " ").strip()
        print(f"       text: {text_preview}...")

    # ==================================================================
    # Phase 3: Agent Response
    # ==================================================================
    print("\n" + "-" * 60)
    print("PHASE 3: Agent Response (what the API returns)")
    print("-" * 60)

    from app.agent import run_sales_agent
    from app.schemas import SalesAgentRequest

    req = SalesAgentRequest(
        sales_rep_id="test_rep",
        customer_id="test_cust",
        session_id="test_session",
        message=query,
    )
    agent_result = run_sales_agent(req)

    print(f"\n  Intent:      {agent_result['intent']}")
    print(f"  Products:    {agent_result['recommended_stripe_products']}")
    print(f"  Escalate:    {agent_result['need_escalation']} -> {agent_result['escalation_team']}")
    print(f"  Confidence:  {agent_result['confidence']:.2f}")
    print(f"  Sources ({len(agent_result['sources'])}):")
    for s in agent_result['sources']:
        print(f"    - {s}")
    print(f"\n  [Internal Answer]")
    print(f"  {agent_result['internal_answer'][:400]}...")
    print(f"\n  [Client-ready Response]")
    print(f"  {agent_result['client_ready_response'][:400]}...")

    t_total = (time.time() - t_start) * 1000
    print(f"\n  Total pipeline latency: {t_total:.0f}ms")

    if idx < len(queries) - 1:
        print("\n\n")
