"""
Hybrid, entity-linked knowledge search over Public Knowledge only.

A small knowledge base is written to a temp directory and indexed into a temp
Milvus Lite file through the ScriptedProvider's deterministic embeddings, so
ingestion, both retrieval legs, fusion and the tool are exercised end to end
with no network. The internal document in the fixture must never surface.
"""

import json

import pytest

from app import database
from app.harness.core import HarnessConfig
from app.harness.provider import Completion, ToolCall
from app.harness.scripted import ScriptedProvider
from app.retrieval import chunking, linking
from app.retrieval.graph import KnowledgeGraph
from app.retrieval.index import KnowledgeIndex, build_index
from tests.conftest import FIXTURE_EMBEDDING_DIM
from tests.conftest import chat as _chat
from tests.conftest import sse_events as _events
from tests.fixture_kb import DOCS, INTERNAL_MARKER

pytestmark = pytest.mark.unit


@pytest.fixture
def index(index_uri) -> KnowledgeIndex:
    idx = KnowledgeIndex(provider=ScriptedProvider(embedding_dim=FIXTURE_EMBEDDING_DIM), milvus_uri=index_uri)
    yield idx
    idx.close()


def _calls(*specs):
    return Completion(
        content="", finish_reason="tool_calls",
        tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=json.dumps(a)) for i, (n, a) in enumerate(specs)),
    )


# =========================================================================
# Ingestion
# =========================================================================
def test_ingestion_indexes_public_chunks_identically_in_both_collections(index):
    dense, sparse = index.dump("dense"), index.dump("sparse")
    assert len(dense) == len(sparse) >= 6
    assert {r["id"] for r in dense} == {r["id"] for r in sparse}
    by_id = {r["id"]: r for r in sparse}
    for row in dense:
        twin = by_id[row["id"]]
        assert (row["text"], row["product"], row["doc_id"], row["source_url"]) == \
               (twin["text"], twin["product"], twin["doc_id"], twin["source_url"])
    assert {r["access_level"] for r in dense} == {"public"}
    assert {r["product"] for r in dense} == {"checkout", "radar", "billing"}


def test_internal_knowledge_is_never_indexed(index):
    everything = json.dumps(index.dump("dense")) + json.dumps(index.dump("sparse"))
    assert INTERNAL_MARKER not in everything
    assert "internal_mock" not in everything and "Discount ladder" not in everything


def test_chunks_carry_their_heading_and_stay_within_the_size_limit():
    body = DOCS["payment/checkout.md"]
    chunks = chunking.chunk_markdown(body, title="Stripe Checkout", max_chars=160)
    assert all(len(c.text) <= 160 + 80 for c in chunks)  # heading prefix may add a little
    assert all(c.text.startswith("Stripe Checkout") for c in chunks)
    assert any("Key Capabilities" in c.heading for c in chunks)
    assert "Access Level" not in " ".join(c.text for c in chunks), "the header block is not content"


def test_tables_are_never_split_from_their_header_row():
    rows = ["## Compare", "", "| Model | Example |", "|---|---|", "| SaaS | Shopify |", "| Marketplace | Uber |", ""]
    chunks = chunking.chunk_markdown("\n".join(rows), title="T", max_chars=40)
    assert len(chunks) == 1 and "| Model | Example |" in chunks[0].text and "| Uber |" in chunks[0].text


def test_ingestion_embeds_through_the_provider(knowledge_base, tmp_path):
    provider = ScriptedProvider(embedding_dim=FIXTURE_EMBEDDING_DIM)
    build_index(provider=provider, knowledge_base=knowledge_base, milvus_uri=str(tmp_path / "k.db"), rebuild=True)
    assert provider.embed_requests, "every chunk vector came from Provider.embed"
    assert INTERNAL_MARKER not in json.dumps(provider.embed_requests), "internal text never even reaches the embedder"


# =========================================================================
# Entity linking and graph expansion
# =========================================================================
def test_vocabulary_comes_from_the_knowledge_graph():
    kg = KnowledgeGraph()
    vocab = linking.vocabulary(kg)
    assert {"checkout", "radar", "billing", "connect", "tax"} <= set(vocab.products)
    assert {"pci_dss", "soc2", "eu", "apple_pay", "enterprise"} <= set(vocab.topics)
    assert "escalation_request" not in vocab.topics and "marketplace" not in vocab.topics, \
        "only products and topics from the graph are in the vocabulary"


def test_linked_products_expand_one_hop_and_topics_resolve_to_products():
    kg = KnowledgeGraph()
    linked = linking.link(kg, question="", products=["checkout"], topics=["soc2"])
    assert linked.products == ["checkout"]
    assert set(kg.related_products("checkout")) <= set(linked.expanded_products)
    assert set(kg.products_for("soc2")) <= set(linked.expanded_products)
    assert "checkout" in linked.expanded_products
    assert "radar" in linked.expanded_products, "Checkout integrates with Radar in the graph"


def test_keyword_fallback_links_when_the_model_names_nothing():
    kg = KnowledgeGraph()
    linked = linking.link(kg, question="How does Radar stop card fraud on our checkout page?", products=[], topics=[])
    assert linked.fallback is True
    assert {"radar", "checkout"} <= set(linked.products)


def test_keyword_fallback_ignores_everyday_words_that_resemble_product_names():
    # The fallback narrows the filter, so a false positive would hide the right documents.
    for question in ("Can I link my bank account?", "Please connect me to a human.",
                     "We run a platform for taxi drivers", "The elements of a good checkout flow"):
        products = linking.keyword_products(question)
        assert not {"link", "connect", "elements"} & set(products), (question, products)


def test_filter_expression_names_the_expanded_products_and_public_only():
    kg = KnowledgeGraph()
    linked = linking.link(kg, question="", products=["billing"], topics=[])
    expr = linking.filter_expr(linked)
    assert expr.startswith("product in [")
    assert '"billing"' in expr and 'access_level == "public"' in expr
    assert linking.filter_expr(linking.link(kg, question="hello", products=[], topics=[])) == 'access_level == "public"'


# =========================================================================
# Search: two legs, fused
# =========================================================================
def test_search_fuses_both_legs_and_returns_sources(index):
    response = index.search("Radar fraud risk scoring machine learning", products=["radar"], topics=[])
    assert response.hits, "something came back"
    top = response.hits[0]
    assert top.product == "radar"
    assert top.dense_rank is not None and top.sparse_rank is not None, "the best chunk was found by both legs"
    assert response.hits == sorted(response.hits, key=lambda h: -h.score)
    assert response.sources[0] == {"title": "Stripe Radar", "url": "https://stripe.com/radar"}
    assert response.filter_expr.startswith("product in [")
    assert "checkout" in response.linked.expanded_products, "one hop from Radar reaches Checkout, so it may appear too"


def test_search_respects_the_expanded_product_filter(index):
    response = index.search("payments", products=["billing"], topics=[])
    assert response.hits
    assert {h.product for h in response.hits} <= set(response.linked.expanded_products)
    for product in response.linked.expanded_products:
        assert f'"{product}"' in response.filter_expr


def test_search_without_entities_searches_all_public_knowledge(index):
    response = index.search("Smart Retries failed subscription payments", products=[], topics=[])
    assert response.linked.fallback is True
    assert response.hits[0].product == "billing"
    assert INTERNAL_MARKER not in json.dumps([h.text for h in response.hits])


# =========================================================================
# Through the HTTP seam: the tool, source extraction, the done event
# =========================================================================
@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider(embedding_dim=FIXTURE_EMBEDDING_DIM)  # must match the fixture index


@pytest.fixture
def harness_config(index_uri):
    return HarnessConfig(milvus_uri=index_uri)


def test_search_knowledge_tool_returns_results_and_the_turn_reports_sources(client, provider):
    provider.script(
        _calls(("search_knowledge", {"question": "Does Checkout support Apple Pay?", "products": ["checkout"], "topics": ["apple_pay"]})),
        "Yes — Checkout supports Apple Pay and Google Pay.",
    )
    with client.stream("POST", "/sales-agent/stream", json={"session_id": "s1", "message": "Does Checkout support Apple Pay?"}) as r:
        events = _events(r.read().decode())

    tool_msg = [m for m in provider.requests[1].messages if m["role"] == "tool"][0]
    payload = json.loads(tool_msg["content"])
    assert payload["linked"]["products"] == ["checkout"] and payload["linked"]["topics"] == ["apple_pay"]
    assert payload["results"] and all("text" in r and "source" in r for r in payload["results"])
    assert INTERNAL_MARKER not in tool_msg["content"]

    done = events[-1][1]
    assert done["sources"][0] == {"title": "Stripe Checkout", "url": "https://stripe.com/payments/checkout"}
    assert len(done["sources"]) == len({(s["title"], s["url"]) for s in done["sources"]}), "de-duplicated"
    assert all(s["url"].startswith("https://") for s in done["sources"]), "no internal:// source ever appears"
    names = [e for e, _ in events]
    assert names[:2] == ["tool_call", "tool_result"]


def test_search_knowledge_schema_enumerates_the_graph_vocabulary(client, provider):
    provider.script("ok")
    _chat(client, "s1", "hi")
    tool = next(t for t in provider.requests[0].tools if t["function"]["name"] == "search_knowledge")
    props = tool["function"]["parameters"]["properties"]
    assert "checkout" in props["products"]["items"]["enum"]
    assert "gdpr" in props["topics"]["items"]["enum"]
    assert tool["function"]["parameters"]["required"] == ["question"]


def test_sources_are_deduplicated_across_calls_and_absent_when_no_search_ran(client, provider):
    provider.script(
        _calls(("search_knowledge", {"question": "fraud", "products": ["radar"], "topics": []}),
               ("search_knowledge", {"question": "risk rules", "products": ["radar"], "topics": []})),
        "ok",
        "no tools this time",
    )
    r1 = _chat(client, "s1", "one")
    r2 = _chat(client, "s1", "two")
    sources = r1.json()["sources"]
    assert sources[0] == {"title": "Stripe Radar", "url": "https://stripe.com/radar"}
    assert sum(1 for s in sources if s["title"] == "Stripe Radar") == 1, "two searches, one entry per source"
    assert r2.json()["sources"] == [], "a turn without search cites nothing"


def test_a_search_served_from_the_tool_cache_still_yields_its_sources(client, provider):
    call = _calls(("search_knowledge", {"question": "fraud scoring", "products": ["radar"], "topics": []}))
    provider.script(call, "first", call, "second")
    r1 = _chat(client, "s1", "one")
    r2 = _chat(client, "s1", "again")
    assert r1.json()["sources"] and r2.json()["sources"] == r1.json()["sources"]
    row = database.get_connection().execute(
        "SELECT cache_hits FROM turn_metrics WHERE session_id='s1' ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    assert row[0] == 1, "the second search was a cache hit, and it still cited its sources"
