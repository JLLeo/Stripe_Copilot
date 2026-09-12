# Stripe Sales Copilot

AI-powered sales enablement agent with KG-enhanced RAG retrieval and a ReAct agent loop. Combines keyword+LLM intent classification, knowledge graph traversal, Milvus vector search, SQL customer lookups, and scenario-specific skill configurations.

---

## Architecture

```
User Query + session_id + customer_id
    │
    ▼
┌─────────────────────────────────────────────────┐
│ CONTEXT MANAGER  │ SQLite session memory        │
│                  │ LLM summarization (4K tokens) │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ INTENT CLASSIFIER │ Keyword (13 KG scenarios)    │
│                   │ + LLM fallback (conf < 0.6)  │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ SKILL INJECTION   │ 14 scenario configs          │
│                   │ system_prompt + tool whitelist│
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ REACT LOOP        │ THINK → ACT → OBSERVE        │
│                   │ max 0-3 iterations           │
│                   │ 6 tools available            │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ SYNTHESIZER       │ LLM generates:               │
│                   │ internal_answer + client      │
│                   │ + sources + escalation        │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│ LOGGER            │ sales_interactions table      │
│                   │ session_memory persistence    │
└─────────────────────────────────────────────────┘
```

## Project Structure

```
stripe-sales-copilot/
├── app/
│   ├── main.py              # FastAPI server (lifespan init + SSE streaming)
│   ├── schemas.py            # Pydantic request/response models
│   ├── agent.py              # Entry point → graph.run_agent()
│   ├── graph.py              # _run_pipeline() core + stream_agent()/run_agent() wrappers
│   ├── tool_cache.py         # Per-session TTL cache for tool results
│   ├── metrics.py            # TurnMetrics collector + aggregate queries
│   ├── skills.py             # 14 SkillConfig definitions
│   ├── tools.py              # 6 LangChain Tools, structured JSON output
│   ├── intent.py             # Keyword+LLM intent classifier (context-aware)
│   ├── context.py            # Session memory + token-aware summarization
│   ├── escalation.py         # Evidence-based escalation gating
│   ├── database.py           # SQLite WAL mode + session_memory table
│   ├── sql_tools.py          # SQL query functions (customer/product/policy)
│   ├── kg_builder.py         # Knowledge graph loader (YAML → networkx)
│   ├── kg_retriever.py       # Query expansion + Milvus filter builder
│   ├── milvus_retriever.py   # Milvus search with KG filter
│   └── milvus_loader.py      # Ingestion: chunk → KG enrich → embed → store
│   └── static/
│       └── index.html        # Chat UI (SSE streaming, session persistence)
├── knowledge_base/
│   ├── payment/              # 8 products
│   ├── revenue/              # 7 products
│   ├── connect/              # Connect platform payments
│   ├── pricing/              # Public + internal pricing docs
│   ├── security/             # Public + internal security docs
│   ├── sales/                # Internal sales playbook
│   └── knowledge_graph.yaml  # 80 entities, 150 relationships
├── data/
│   └── stripe_sales_copilot.db  # SQLite: 5 tables + session_memory + turn_metrics
├── milvus.db/                # Milvus Lite (278 chunks, 1536-dim)
├── tests/                    # pytest suite — 198 unit + 5 integration-marked
│   ├── conftest.py           # sys.path bootstrap + excludes integration/
│   ├── test_escalation.py    # Escalation gating logic
│   ├── test_kg_retriever.py  # Keyword matching + graph traversal
│   ├── test_intent.py        # Intent classification
│   ├── test_tool_cache.py    # Tool result cache
│   ├── test_skills.py        # Skill registry integrity
│   ├── test_context.py       # Context window management
│   ├── test_tools.py         # Structured tool output
│   ├── test_metrics.py       # Turn metrics collection
│   └── integration/          # Runnable scripts (NOT collected by pytest)
│       ├── README.md         # How to run them
│       ├── test_e2e.py       # End-to-end multi-turn conversations
│       ├── test_agent.py     # Full pipeline demo → writes result.md
│       ├── test_all_tools.py # All 6 tools across scenarios
│       ├── test_multiturn.py # Multi-turn context retention
│       ├── test_retrieve.py  # KG → Milvus pipeline
│       └── test_milvus.py    # Raw Milvus retrieval
├── ARCHITECTURE.md           # Detailed design document
├── requirements.txt
└── .env
```

## Setup

```bash
# Virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install
pip install -r requirements.txt

# Configure
# Edit .env: OPENAI_API_KEY=sk-...

# Build Milvus index (first time only)
python -m app.milvus_loader --force

# Start server
python -m uvicorn app.main:app --reload

# Open Chat UI
http://127.0.0.1:8000/

# Or API docs
http://127.0.0.1:8000/docs
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Chat UI (interactive frontend) |
| `GET` | `/api/customers` | Customer list for dropdown |
| `POST` | `/sales-agent/chat` | Sync chat (JSON response) |
| `POST` | `/sales-agent/stream` | Streaming chat (SSE, real-time stages) |
| `POST` | `/sales-agent/confirm-escalation` | Confirm escalation (mock human handoff) |
| `GET` | `/api/metrics?days=7` | Agent observability: latency, tokens, cache hit rate, per-intent breakdown |

## Frontend Features

- **Real-time pipeline visualization:** Intent → Skill → THINK → ACT → OBSERVE → SYNTH → Escalation
- **Session persistence:** `session_id` stored in `localStorage`, survives page refresh
- **Multi-turn context:** Previous turns loaded from SQLite, injected into intent + LLM
- **Customer auto-load:** Selecting a customer auto-fetches profile + product usage from SQL, injected into every request without LLM needing to call a tool
- **Customer selector:** Dropdown populated from `/api/customers`, auto-saved
- **Copy-to-clipboard:** One-click copy for client-ready responses
- **Multi-intent handling:** All matched scenarios tracked; secondary intents injected with domain guidance
- **Out-of-scope detection:** Irrelevant queries blocked; Stripe signal words prevent false out-of-scope
- **Context management:** 3-layer sliding window (summary → recent raw → older truncated), LLM compression, per-turn truncation at sentence boundaries
- **Anti-placeholder:** Customer names auto-injected into prompts, signatures/placeholders blocked
- **Escalation confirmation:** Three-tier (rule → context LLM → stay), user confirms before routing, mock human handoff
- **Tool result caching:** Per-session TTL cache — repeated lookups skip SQL/Milvus entirely
- **Observability:** Every turn records intent path, tools, tokens, per-stage latency, cache hits to SQLite
- **Dark theme:** Stripe-inspired color palette

## Testing

### Unit tests (fast — no LLM, no Milvus)

```bash
# Full unit suite: 198 tests in ~5s
pytest -m "not integration"

# Single module
pytest tests/test_escalation.py

# With coverage
pytest -m "not integration" --cov=app --cov-report=term-missing
```

| Test file | Tests | Covers |
|---|---|---|
| `tests/test_escalation.py` | 46 | Escalation gating, trigger matching, volume thresholds |
| `tests/test_kg_retriever.py` | 39 | Keyword matching, graph traversal, filter building |
| `tests/test_intent.py` | 23 (+4 integration) | Intent classification, out-of-scope, context inheritance |
| `tests/test_tool_cache.py` | 21 | Cache keys, TTL expiry, session isolation, bounds |
| `tests/test_skills.py` | 19 | Skill registry integrity, tool name validity |
| `tests/test_context.py` | 18 | Token budget, truncation, layered assembly |
| `tests/test_tools.py` | 16 (+1 integration) | Structured JSON output, registry consistency |
| `tests/test_metrics.py` | 16 | Metric collection, token accounting, stage latency |

### Integration scripts (calls LLM + Milvus)

These live in `tests/integration/` and are **standalone scripts, not pytest
modules** — their code runs at import time, so `tests/conftest.py` keeps pytest
from collecting them. Run them directly; they work from any directory.

```bash
# End-to-end multi-turn conversations (4 scenarios, 12 turns)
python tests/integration/test_e2e.py

# All-tool coverage test
python tests/integration/test_all_tools.py

# Multi-turn context retention
python tests/integration/test_multiturn.py

# Full Agent pipeline demo with stage-by-stage output → writes result.md
python tests/integration/test_agent.py
python tests/integration/test_agent.py "SaaS subscription billing Europe VAT handling"

# KG → Milvus pipeline (retrieval only, no agent loop)
python tests/integration/test_retrieve.py

# Raw Milvus retrieval (no KG, no agent)
python tests/integration/test_milvus.py
```

The 5 `@pytest.mark.integration` tests inside `tests/test_intent.py` and
`tests/test_tools.py` are genuine pytest tests and stay in the pytest tree —
they are separated by marker, not by directory.

## Key Numbers

| Metric | Value |
|---|---|
| Knowledge base docs | 21 markdown files |
| KG entities / relationships | 80 / 150 |
| Milvus chunks | 278 (1536-dim, COSINE) |
| Intent scenarios | 13 classifiable (12 product + escalation_request) |
| Skill configs | 14 (13 + out_of_scope terminal state) |
| Tools | 6 (1 RAG + 3 SQL + 1 file read + 1 decision) |
| Escalation tiers | 3 (rule → context LLM → stay) |
| Auto-escalate scenarios | 4 of 14 |
| Escalation teams | 7 |
| Unit tests | 198 (~5s, no external deps) + 5 integration |
| Tool output format | Structured JSON (`_ok` / `_empty` / `ERROR:`) |
| Tool cache | 15 min TTL, 50 entries/session, 200 sessions |
| Metrics per turn | intent path, tools, tokens, stage latency, cache hits |
| Context layers | 3 (summary → recent raw → older truncated) |
| Conversation retention | Last 3 turns raw, older LLM-compressed |
| SQL tables in use | 7 (5 existing + session_memory + turn_metrics) |
| LLM calls per query | 3-6 (THINK×N + SYNTH×2, optional INTENT/escalation fallback) |
| Max ReAct iterations | 0-3 per scenario (measured avg 1.30) |
| Measured avg latency | 9.9s over 20 turns (SYNTH is 60-70%) |
| Measured cost | ≈ $0.0008 per turn (gpt-4o-mini) |
