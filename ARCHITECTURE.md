# Stripe AI Sales Agent — Architecture

How the code implements the decisions in [`docs/adr/`](docs/adr/), using the
vocabulary in [`CONTEXT.md`](CONTEXT.md). This document describes what exists on the
branch now; sections marked *arrives with #N* point at the ticket that adds them.

## Overview

The agent talks directly to a Stripe customer or prospect. Each turn, the model is
given a fixed-order prompt and asked to reply; the harness around it builds the
request, streams the answer, appends both sides to working memory, and records what
the turn cost. There is no intent classifier, no scenario router, and no forced tool
call anywhere in the path — the model decides, deterministic code guards
([ADR 0001](docs/adr/0001-model-decides-guardrails-constrain.md)).

```
HTTP (FastAPI)                 Harness                              Provider
───────────────                ───────                              ────────
POST /sales-agent/stream ──►  run_turn(session, customer, msg)
                               ├─ load_session ─ or ─ SessionStart hooks ─► customer block
                               ├─ assemble: [static system][customer block][messages…][user]
                               ├─ provider.complete(request) ─────────────► DeepSeek (stream)
                               │     TextDelta ──► SSE text_delta            reasoning_content
                               │     ReasoningDelta ──► SSE thinking (once)  tool_calls (#4)
                               │     Completed ──► usage
                               ├─ append_messages(user, assistant)
                               ├─ record_turn(tokens, cache hit/miss, latency)
                               └─ SSE done { reply, usage, latency_ms }
```

## Harness — `app/harness/`

### The turn — `core.py`

`Harness.run_turn(session_id, customer_id, message)` is a generator of `TurnEvent`s
(`thinking`, `text_delta`, `done`, `error`). The transport layer forwards them as
Server-Sent Events or, for the synchronous endpoint, keeps only the last one.

1. **Session binding.** An unseen `session_id` triggers **SessionStart**: the Customer
   Profile and product usage are loaded from the seed database and the SessionStart
   hooks render the customer block, which is frozen into the `sessions` row. Later
   turns reuse that exact text, so the block can never drift mid-session
   ([ADR 0005](docs/adr/0005-append-only-prompt-prefix.md)). A session with no
   `customer_id` is a Prospect; its block says so.
2. **Request assembly** in the fixed order — see below.
3. **Completion.** The Provider streams; text deltas are forwarded immediately, the
   first reasoning delta is announced once as `thinking`, and the final `Completed`
   event carries usage.
4. **Working memory.** The customer message and the assistant reply (with its
   `reasoning_content`, which DeepSeek requires back once tools are in play) are
   appended as two `messages` rows. Nothing is ever updated.
5. **Metrics.** One `TurnRecord`: model, prompt/completion/reasoning tokens,
   `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`, latency, error.

A provider failure — after the client library's own retries — ends the turn with an
`error` event carrying a fixed friendly message, records the turn with the error
class, and appends nothing, so the next message starts from unchanged working memory.
If the customer disconnects mid-reply the turn is still metered (error
`ClientDisconnected`) and, again, nothing is appended.

`HarnessConfig` (main model `deepseek-v4-pro`, `max_tokens`, `thinking`) is read
from `HARNESS_*` environment variables. Session binding is strict: an unknown
`customer_id` is refused (HTTP 404) rather than downgraded to a prospect, and a session
never switches customer (HTTP 409).

### Prompt assembly — `prompt.py`

Every request is built in this order and only this order:

| Position | Content | Stability |
|---|---|---|
| `messages[0]` system | **Static prompt**: role, conduct (mirror the customer's language, admit being an AI, decline out-of-scope), the never-do list (no custom pricing, no roadmap promises, no tax/legal advice, no security documents, no fraud guarantees, no internal guidance), then the active rows of `sales_policy_updates` sorted by area and title | identical for every session in the process; rendered once at startup |
| `tools` | tool definitions | empty — *arrives with #4* |
| `messages[1]` system | **Customer block**: profile fields and products in use, or the prospect notice | identical for the life of the session |
| `messages[2:]` | working memory, oldest first, then the new customer message | append-only |

No dates, timestamps, or identifiers appear anywhere before the newest message; a test
asserts the serialized prefix is byte-identical between consecutive turns. On the live
model this gives cache hits from the second turn onward (see README, "Measured").

### Hooks — `hooks.py`

`HookEvent` names the five moments — `SessionStart`, `PreToolUse`, `PostToolUse`,
`Stop`, `SessionEnd` — and `HookRegistry` keeps hooks per event. Only `SessionStart`
has a dispatcher today: each registered hook receives the session, profile and usage
and returns text for the customer block. The
tool-side events and their allow / deny-with-feedback / pause outcomes *arrive with #4*
and *#8*.

### The Provider seam — `provider.py`

The only path to a model. `complete(CompletionRequest) -> Iterator[StreamEvent]`
streams `TextDelta` / `ReasoningDelta` events and ends with `Completed(completion)`;
`embed(texts)` returns vectors. `CompletionRequest` carries the wire-shaped
`messages` and `tools`, `max_tokens`, and the DeepSeek `thinking` switch. Two
adapters exist, which is what makes it a real seam:

- **`DeepSeekProvider`** (`deepseek.py`) — DeepSeek's OpenAI-compatible Chat
  Completions API through the `openai` client (`stream_options.include_usage`,
  `extra_body={"thinking": …}`), accumulating text, reasoning and tool-call deltas
  into one `Completion`; embeddings from OpenAI `text-embedding-3-small`, because
  DeepSeek has no embedding endpoint and the Milvus index is 1536-dimensional
  ([ADR 0002](docs/adr/0002-hand-built-harness-on-deepseek.md)). Transient errors are
  retried by the client (`max_retries=3`).
- **`ScriptedProvider`** (`scripted.py`) — plays back a script (text, full
  `Completion`s, or exceptions) in word-sized deltas, returns deterministic unit-vector
  embeddings, and records every `CompletionRequest`. The recorded requests are the
  test suite's window into the prompt.

## Transport — `app/main.py`

FastAPI owns one `Harness`, built at startup from the environment unless a test placed
its own on `app.state.harness` first.

| Endpoint | Behaviour |
|---|---|
| `POST /sales-agent/chat` | runs a turn, returns the `done`/`error` payload as `ChatResponse` |
| `POST /sales-agent/stream` | runs a turn as SSE: `event: <name>\ndata: <json>\n\n` |
| `GET /api/customers` | sign-in selector |
| `GET /api/metrics?days=N` | `summary()` — turns, errors, avg latency, avg tokens, cache hit rate |
| `GET /` | the chat UI |

The UI (`static/index.html`) is a single page: a sign-in-as-customer selector, a
streamed conversation, and per-reply latency / token / cache-hit figures. The session
id lives in `localStorage` per customer.

## Data layer

### SQLite — `data/seed.db` + `data/runtime.db`

Two files, one connection. The **seed database** is tracked, rebuilt from `data.xlsx`
by `scripts/build_seed_db.py`, and opened read-only; the **runtime database** is
gitignored and created on first start.

| Database | Table | Purpose |
|---|---|---|
| seed | `customers` (30) | Customer Profile |
| seed | `stripe_products` (26) | product catalogue |
| seed | `customer_product_usage` (81) | products in use per customer |
| seed | `sales_policy_updates` (20) | the policy register rendered into the static prompt |
| runtime | `sessions` | session → customer binding and the frozen customer block |
| runtime | `messages` | working memory, one row per message, insert-only |
| runtime | `turn_metrics` | one row per turn |

`get_connection()` opens the runtime file as the main database (`WAL`,
`busy_timeout=5000`, `foreign_keys=ON`) and `ATTACH`es the seed file with `mode=ro`.
Unqualified table names resolve to whichever file holds them, so callers never learn
the split and a write to a seed table fails instead of dirtying a tracked file.
`database.py` is the only module that knows which table lives where. The seed is built
with a rollback journal so no `-wal`/`-shm` sidecars appear beside a tracked file.
`SEED_DB_PATH` / `RUNTIME_DB_PATH` override the locations; the test suite points the
runtime at a temp file for the whole run.

### Knowledge graph — `knowledge_base/knowledge_graph.yaml` (retained, *rewired in #6*)

80 nodes, 150 edges, loaded into a `networkx.DiGraph` at first use: products, payment
methods, compliance topics, geographies, customer types, and the relationships between
them (`integrates_with`, `supports_method`, `suitable_for`, `complies_with`, …).
`kg_retriever.py` links a query to entities and expands one hop to build a scalar
filter; in the new design the model does the linking and the graph does the expansion
([ADR 0004](docs/adr/0004-hybrid-retrieval-via-sibling-collection.md)).

### Milvus — `milvus.db` (Milvus Lite; retained, *rewired in #6*)

Collection `stripe_sales_knowledge`, 278 chunks, 1536-dim, COSINE. Ingestion enriches
each chunk with KG metadata (`related_products`, `supports_methods`, `complies_with`)
and an `access_level`. #6 rebuilds ingestion to index public chunks only, adds the
BM25 sibling collection, and moves embeddings onto the Provider seam.

## Observability — `app/metrics.py`

`TurnRecord` → `turn_metrics`. `summary(days)` returns turn count, error count,
average latency, average prompt / completion / reasoning tokens, total cache hit and
miss tokens, and `cache_hit_rate = hit / (hit + miss)`. Prompt-cache hit rate is a
first-class number because the prefix discipline in ADR 0005 is easy to break by
accident and this is where a break shows first.

## Testing

68 tests, no network, one temp runtime database per run, ~4 s. The app under test
always starts with a harness over a `ScriptedProvider` (installed by `conftest.py`), so
the suite runs with no `.env` and no keys.

Two seams only ([issue #1](https://github.com/JLLeo/Stripe_Copilot/issues/1), Testing
Decisions): the **HTTP API** is the test surface and the **Provider** is the
substitution point. A test scripts the provider, drives the endpoints with FastAPI's
`TestClient`, then asserts on the response, the recorded requests, and the runtime
database. The DeepSeek adapter's stream handling is covered against a stub of the
OpenAI client. Evaluation runs against the real provider *arrive with #12*.

## What arrives next

| Ticket | Adds |
|---|---|
| #4 | tool registry, `PreToolUse` / `PostToolUse` dispatch, `Skill` loading, profile / product / pricing tools, `turn_budget`, `result_cap`, tool cache |
| #5 | `ask_customer`, `Stop` guardrails (`anti_placeholder`, `internal_canary`) |
| #6 | public-only ingestion, hybrid dense + BM25 search, model-driven entity linking, LangChain removed |
| #7 | the `research` sub-agent |
| #8 | Handoff with customer confirmation, the seven Teams, policy skills |
| #9 | prospect discovery and lead capture |
| #10 | Customer Memory and Reflection |
| #11 | attachments, tool-result clearing, compaction with hysteresis |
| #12 | evaluation suite |
| #13 | final documentation pass |
