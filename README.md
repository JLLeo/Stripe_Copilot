# Stripe AI Sales Agent

A customer-facing AI sales agent for Stripe, built on a hand-written harness in the
style of Claude Code: the model decides what to do on every turn; deterministic code
only builds the request, moves bytes, and guards the edges.

This branch is a ground-up rebuild in progress. What exists today is the first
tracer bullet — a customer signs in, asks a question, and gets a streamed answer
through the new harness, with prompt-cache metrics on every turn. Tools, skills,
retrieval, handoff, and memory land ticket by ticket
([issues #4–#13](https://github.com/JLLeo/Stripe_Copilot/issues/1)).

---

## How a turn works

```
customer message  ─►  /sales-agent/stream
                          │
                          ▼
             ┌─────────────────────────────┐
             │ Harness.run_turn            │
             │  1. SessionStart (first     │   customer block frozen from
             │     contact only)           │   the Customer Profile
             │  2. assemble request        │   fixed order, append-only
             │  3. Provider.complete       │   DeepSeek, streamed
             │  4. append both messages    │   working memory
             │  5. record TurnRecord       │   tokens, cache hit/miss, latency
             └─────────────────────────────┘
                          │
                          ▼
        SSE: thinking? · text_delta* · done | error
```

Every request is built in the same order — static system prompt, tool definitions
(none yet), customer block, working memory — and nothing before the newest message
is ever rewritten. DeepSeek's context cache is a prefix match, so on a real two-turn
session 1,024 of the second turn's 1,169 prompt tokens were served from cache.

The design decisions behind this are recorded in [`docs/adr/`](docs/adr/) and the
vocabulary in [`CONTEXT.md`](CONTEXT.md).

## Project structure

```
stripe-sales-copilot/
├── app/
│   ├── main.py               # FastAPI transport: chat, SSE stream, customers, metrics
│   ├── schemas.py            # ChatRequest / ChatResponse
│   ├── database.py           # One connection over seed.db (read-only) + runtime.db
│   ├── metrics.py            # TurnRecord + /api/metrics summary (cache hit rate)
│   ├── harness/
│   │   ├── provider.py       # The Provider seam: CompletionRequest → stream of events
│   │   ├── deepseek.py       # Production adapter: DeepSeek chat + OpenAI embeddings
│   │   ├── scripted.py       # Test adapter: plays a script, records every request
│   │   ├── prompt.py         # Static system prompt, customer block, fixed-order assembly
│   │   ├── hooks.py          # Hook events; SessionStart dispatch
│   │   └── core.py           # Harness.run_turn — the loop
│   ├── kg_builder.py         # Knowledge graph loader (retained; rewired in #6)
│   ├── kg_retriever.py       # Entity linking + graph expansion (retained; rewired in #6)
│   ├── milvus_retriever.py   # Milvus search (retained; rewired in #6)
│   ├── milvus_loader.py      # Ingestion (retained; rewritten in #6)
│   └── static/index.html     # Customer chat UI
├── data/
│   ├── seed.db               # Tracked, read-only: customers, products, usage, policies
│   └── runtime.db            # Gitignored, created on first start: sessions, messages, metrics
├── scripts/build_seed_db.py  # Rebuild data/seed.db from data.xlsx
├── knowledge_base/           # Public + internal product docs, knowledge graph
├── milvus.db/                # Milvus Lite index (278 chunks)
├── tests/                    # 68 tests, no network, ~4s
├── docs/adr/                 # Architecture decision records
├── CONTEXT.md                # Domain glossary
└── ARCHITECTURE.md
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# .env
DEEPSEEK_API_KEY=sk-...      # chat model (deepseek-v4-pro)
OPENAI_API_KEY=sk-...        # embeddings only (text-embedding-3-small)

# Rebuild the seed database — only after editing data.xlsx; data/seed.db is tracked
python scripts/build_seed_db.py

# Run
python -m uvicorn app.main:app --reload
# UI     http://127.0.0.1:8000/
# Docs   http://127.0.0.1:8000/docs
```

Optional environment: `HARNESS_MAIN_MODEL`, `HARNESS_MAX_TOKENS`,
`HARNESS_THINKING=enabled|disabled`, `SEED_DB_PATH`, `RUNTIME_DB_PATH`.

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Customer chat UI |
| `GET` | `/api/customers` | Customers for the sign-in selector |
| `POST` | `/sales-agent/chat` | One turn, JSON reply. `404` unknown customer, `409` session already bound to another customer |
| `POST` | `/sales-agent/stream` | One turn as SSE: `thinking`?, `text_delta`*, then `done` or `error` |
| `GET` | `/api/metrics?days=7` | Turns, errors, latency, tokens per turn, prompt-cache hit rate |

Request body for both chat endpoints:

```json
{ "session_id": "uuid", "customer_id": "CUST-001", "message": "What does Checkout do?" }
```

`customer_id` may be omitted: the session is then a prospect with no profile. A session is bound to its
customer on first contact and refuses to switch.

## Testing

```bash
pytest            # 68 tests in ~4s; no model calls, temp runtime database
```

All behavioural tests drive the HTTP API with a `ScriptedProvider` standing in for
DeepSeek. The fake records every request the harness built, which is how tests assert
things the response never shows — that the prefix is byte-identical between turns,
what the customer block contained, that no timestamp leaked into the cached prefix.

| Test file | Covers |
|---|---|
| `tests/test_harness_chat.py` | The turn end to end: fixed order, prefix stability, SessionStart block, prospect sessions, unknown/mismatched customer, SSE incl. `thinking`, friendly failure, disconnect metering, metrics |
| `tests/test_providers.py` | The Provider seam: scripted playback, deterministic embeddings, DeepSeek stream accumulation and request shape |
| `tests/test_database.py` | Seed / runtime split, read-only seed, append-only messages |
| `tests/test_api_customers.py` | Customer list served through the shared connection |
| `tests/test_kg_retriever.py` | Knowledge-graph entity matching and expansion (retained module) |

Running the suite leaves `git status` clean: the suite uses its own runtime database.

## Measured on the live model

Two-turn session, `deepseek-v4-pro`, thinking enabled:

| | Turn 1 | Turn 2 |
|---|---|---|
| Prompt tokens | 1,130 | 1,169 |
| Cache hit / miss | 0 / 1,130 | **1,024 / 145** |
| Reasoning tokens | 128 | 126 |
| Latency | 3.7 s | 2.8 s |

## Documents

- [`CONTEXT.md`](CONTEXT.md) — the glossary: Harness, Turn, Guardrail, Hook, Skill, Handoff, Customer Memory, Compaction, …
- [`docs/adr/`](docs/adr/) — why the model decides and rules only guard (0001), why the harness is hand-built on DeepSeek (0002), why internal knowledge never enters a customer conversation (0003), hybrid retrieval via a sibling collection (0004), the append-only prompt prefix (0005), tiered context-pressure relief (0006)
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — how the current code implements them
