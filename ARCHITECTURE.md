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
                               ├─ assemble: [static system][customer block][messages…][user] + tools
                               ├─ loop:
                               │   provider.complete(request) ──────────────► DeepSeek (stream)
                               │     TextDelta ──► SSE text_delta              reasoning_content
                               │     ReasoningDelta ──► SSE thinking (once)    tool_calls
                               │     Completed ──► usage, tool_calls
                               │   for each tool call:
                               │     PreToolUse hooks ─► Allow | Deny(feedback) | Replace(cached)
                               │     tool.run ─► PostToolUse hooks (result_cap, cache store)
                               │     SSE tool_call · skill_loaded | tool_result | hook_blocked
                               │   until the reply has no tool calls
                               ├─ append_messages(user, assistant, tool…, assistant)
                               ├─ record_turn(tokens, cache hit/miss, tools, skills, hooks, rounds)
                               └─ SSE done { reply, usage, latency_ms, tool_rounds }
```

## Harness — `app/harness/`

### The turn — `core.py`

`Harness.run_turn(session_id, customer_id, message)` is a generator of `TurnEvent`s
(`thinking`, `tool_call`, `skill_loaded`, `tool_result`, `hook_blocked`,
`subagent_started`, `subagent_tool_call`, `subagent_finished`, `handoff_pending`,
`text_delta`, `done`, `error`). The transport layer forwards them as Server-Sent Events or, for the
synchronous endpoint, keeps only the last one.

1. **Session binding.** An unseen `session_id` triggers **SessionStart**: the Customer
   Profile and product usage are loaded from the seed database and the SessionStart
   hooks render the customer block, which is frozen into the `sessions` row. Later
   turns reuse that exact text, so the block can never drift mid-session
   ([ADR 0005](docs/adr/0005-append-only-prompt-prefix.md)). A session with no
   `customer_id` is a Prospect; its block says so.
2. **Request assembly** in the fixed order — see below.
3. **Completion.** The Provider streams; text deltas are forwarded immediately, the
   first reasoning delta is announced once as `thinking`, and the final `Completed`
   event carries usage and any tool calls.
4. **Tool rounds.** While the reply carries tool calls, each call goes through the
   `PreToolUse` hooks (allow, deny with feedback, replace with a cached result, or
   pause), the tool runs, the `PostToolUse` hooks may rewrite the result, and a `tool`
   message is appended; then the model is called again with everything so far. A round
   is one model response with tool calls; several calls in one response run in order and
   all their results go back together. Unknown tools, malformed arguments, missing
   required arguments and tool exceptions all come back to the model as feedback in
   the tool message — the customer never sees them. A **pause** ends the turn at that
   call: the remaining calls of the round get a "not run" result, the messages so far are
   appended, and `done` carries the question for the customer; the paused call's result
   arrives with their answer (see Handoff).
5. **Working memory.** The customer message and every assistant and tool message of
   the turn (assistant rows with their `reasoning_content`, which DeepSeek requires
   back whenever `tools` are present) are appended as `messages` rows. Nothing is
   ever updated.
6. **Metrics.** One `TurnRecord`: model, prompt/completion/reasoning tokens summed over
   the turn's rounds, `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`, provider
   calls, tool rounds, tools called, skills loaded, hook outcomes, tool-cache hits,
   latency, error.

A provider failure — after the client library's own retries — ends the turn with an
`error` event carrying a fixed friendly message, records the turn with the error
class, and appends nothing, so the next message starts from unchanged working memory.
If the customer disconnects mid-reply the turn is still metered (error
`ClientDisconnected`) and, again, nothing is appended.

`HarnessConfig` (main model `deepseek-v4-pro`, sub-agent model `deepseek-flash`,
`max_tokens`, `thinking`, `skills_dir`, `tool_round_budget`, `subagent_max_rounds`,
`result_cap_chars`, `tool_cache_ttl_seconds`, `milvus_uri`) is read from `HARNESS_*`
environment variables. Session binding is strict: an unknown
`customer_id` is refused (HTTP 404) rather than downgraded to a prospect, and a session
never switches customer (HTTP 409).

### Prompt assembly — `prompt.py`

Every request is built in this order and only this order:

| Position | Content | Stability |
|---|---|---|
| `messages[0]` system | **Static prompt**: role, conduct (mirror the customer's language, admit being an AI, decline out-of-scope), the never-do list (no custom pricing, no roadmap promises, no tax/legal advice, no security documents, no fraud guarantees, no internal guidance), the active rows of `sales_policy_updates` sorted by area and title, then the **skill index** — one line per skill, descriptions only | identical for every session in the process; rendered once at startup |
| `tools` | tool definitions from the registry, in registration order: `Skill`, `get_my_profile`, `list_products`, `get_pricing` | identical for every request in the process |
| `messages[1]` system | **Customer block**: profile fields and products in use, or the prospect notice | identical for the life of the session |
| `messages[2:]` | working memory, oldest first, then the new customer message | append-only |

No dates, timestamps, or identifiers appear anywhere before the newest message; a test
asserts the serialized prefix is byte-identical between consecutive turns. On the live
model this gives cache hits from the second turn onward (see README, "Measured").

### Skills — `skills.py`, `skills/<name>/SKILL.md`

A skill is a markdown file with YAML frontmatter (`name` must match its directory;
`description` is one line, ≤200 characters) and a body. `load_skills()` validates every
file when the harness is built, so a broken skill fails startup, not a conversation.
The static prompt carries only the index of descriptions; the body reaches the model
as the result of the `Skill(name)` tool, whose `name` parameter is an enum of the loaded
skills. Several skills may be loaded in one round. Skills recommend tools in prose and
carry no allowlist — restricting tools by skill would be a router, not a guardrail
([ADR 0001](docs/adr/0001-model-decides-guardrails-constrain.md)).

Seven product skills exist, authored from the public product documentation only
([ADR 0003](docs/adr/0003-internal-knowledge-never-enters-customer-context.md)):
`payments`, `billing`, `connect`, `tax`, `fraud_protection`, `terminal`, `data`. Each
gives the model the products in the area, when to recommend which, what to establish
first, public pricing, and when to offer a human.

### Tools — `tools.py`, `app/tools/`

A `Tool` is a name, a description, a JSON schema and a function
`(ToolContext, arguments) -> ToolResult`. The `ToolRegistry` renders definitions in
registration order (they are part of the cached prefix), parses arguments and checks
them against `required` and `properties`, and turns tool exceptions into error results.
Results are compact JSON — they live in every later request of the session.

| Tool | Source | Notes |
|---|---|---|
| `Skill(name)` | `skills/` | not cacheable: a load must always land in the conversation |
| `get_my_profile()` | seed `customers` + `customer_product_usage` | no parameters; reads the session's bound customer, so another customer cannot be named |
| `list_products(group?)` | seed `stripe_products` | name, group, one-line description |
| `get_pricing(product)` | the `## Price` section of every knowledge-base document whose header says `Access Level: public`, plus the three price sections of the pricing overview | the seed database holds no prices, so the parent spec's "pricing from SQL" became "pricing from Public Knowledge"; documents not marked public are never opened, and when nothing matches the tool says so rather than guessing |
| `search_knowledge(question, products[], topics[])` | the knowledge index (below) | `products` and `topics` are enums from the graph; results carry passages and sources; `meta.sources` feeds `source_extraction`. Its description says: use this first; hand multi-product, comparative or thin results to `research` |
| `research(question)` | a Sub-agent (below) over `search_knowledge` | returns `{brief, sources, tool_calls, stopped_by_cap, gave_up}`; the documents the brief cites in `[Title]` form are its sources (a brief that cites nothing keeps everything it read); `meta.subagent` carries its metering |
| `request_handoff(team, reason, evidence)` | `handoffs` (runtime) | never runs inside a turn: `handoff_confirmation` pauses first, and the customer's answer produces its result (see Handoff) |

### Sub-agents — `subagent.py`, `app/tools/research.py`

A Sub-agent is a tool whose implementation is a small agent of its own: `run_subagent()`
takes a `SubagentSpec` (name, model, system prompt, a `ToolRegistry` holding only the
tools it may call, a round cap, and the wording to use when the budget runs out) and a
task, and runs the same request → tool → request loop as the harness in a fresh message
list — system prompt and task only. Nothing from the main conversation goes in (no static
prompt, no customer block, no working memory) and nothing but the Brief comes out, so
however much the sub-agent reads, the main context grows by one tool result
([ADR 0006](docs/adr/0006-context-pressure-relieved-in-tiers.md)). A round is one model
response with tool calls, so parallel calls in one response count once. After
`max_rounds` rounds the next request carries `tool_choice="none"` and the spec's
cap note; a model that still asks for tools gets the spec's fallback brief and the
result is marked `gave_up`. Results it reads are capped like the harness's, and the
sources they carry are collected.

`research` is the first sub-agent: `deepseek-flash`, `search_knowledge` as its only tool,
3 rounds, a system prompt that asks for a ≤200-word brief with `[Source Title]` after
every factual statement and a closing line on what could not be confirmed.

**Progress reaches the customer as it happens.** A tool reports progress through
`ToolContext.emit`. The harness runs each tool on a worker thread and yields the events
it emits while it runs, so the stream carries `tool_call(research)` before the sub-agent
has made a single request, then `subagent_started`, one `subagent_tool_call` per search
as each happens, `subagent_finished`, and finally the `tool_result`. The sub-agent's
model calls and tokens are metered apart from the main model's (`subagent_calls` counts
delegations; `subagent_prompt_tokens` / `subagent_completion_tokens` their cost), so
`done.usage` remains the cost of the conversation the customer is in; a brief served from
the tool cache is not booked as a new delegation. The same runner will serve Reflection
(#10).

### Hooks and guardrails — `hooks.py`, `guardrails.py`

`HookEvent` names the five moments — `SessionStart`, `PreToolUse`, `PostToolUse`,
`Stop`, `SessionEnd` — and `HookRegistry` keeps hooks per event in registration order.

- **SessionStart** hooks return text for the customer block.
- **PreToolUse** hooks return `Allow`, `Deny(feedback)`, `Replace(result)` or
  `Pause(event, data, reply)`; the first deny, replace or pause wins. A deny becomes the
  tool message `Blocked by <hook>: <feedback>` and the loop continues, so the model reads
  why and adjusts. A pause ends the turn and asks the customer.
- **PostToolUse** hooks may return a modified `ToolResult`. They run on served (cached)
  results as well as fresh ones, so `source_extraction` sees every search the model
  relied on; `tool_cache_store` skips results that came from the cache.
- `Stop` and `SessionEnd` gain dispatchers with *#5* and *#10*.

| Guardrail | Hook | Rule |
|---|---|---|
| `turn_budget` | PreToolUse | after 8 rounds of tool calls in a turn, every further call is denied and the turn is marked exhausted; the next request carries `tool_choice="none"`, so the model must answer in text. If it still asks for tools, the harness stops the turn with a fixed "here is what I have so far" reply (`hard_stop`) rather than looping on denials |
| `tool_cache_lookup` | PreToolUse | an identical call (tool + arguments) within the session is replaced by the cached result (TTL 15 min, 50 entries per session, 200 sessions) |
| `result_cap` | PostToolUse | results over 6,000 characters (~1.5K tokens) are cut at a JSON element, sentence or line boundary with a `[truncated: showing N of M characters]` note |
| `tool_cache_store` | PostToolUse | successful cacheable results enter the cache |
| `source_extraction` | PostToolUse | sources a tool cites (`meta.sources`) are collected on the turn, de-duplicated, and returned in `done.sources` |
| `handoff_validity` | PreToolUse | `request_handoff` with an unknown team, empty evidence, or evidence that matches nothing the customer said (a passage, or ≥60% of its whole words) and names no actual profile value is denied with feedback — field names alone never count |
| `enterprise_volume` | PreToolUse | a customer whose profile shows more than $10M annual payment volume can only be handed to Enterprise Sales; anything else is denied with feedback naming the rule |
| `handoff_confirmation` | PreToolUse | every valid `request_handoff` creates a pending `handoffs` row and pauses the turn with `handoff_pending` |

Metrics record every hook outcome: `allowed`, `denied`, `replaced` (served from cache), `modified` (a PostToolUse hook rewrote the result), `paused`, `hard_stop`.

### Handoff — `app/tools/handoff.py`

The customer-facing form of Claude Code's permission prompt. Seven canonical Teams
(`Enterprise Sales`, `Deal Desk / Pricing`, `Solutions Engineering`, `Security &
Compliance`, `Tax Specialist`, `Risk / Fraud`, `Sales Representative`) with a
one-line remit each, rendered into the `request_handoff` description; the policy
register's own team names map onto them (`team_for_policy`), and every policy line in
the static prompt ends with "→ hand off to <Team>", so the model learns which team from the
same text that states the rule.

The flow: the model calls `request_handoff(team, reason, evidence)` → `handoff_validity`
and `enterprise_volume` may deny with feedback → `handoff_confirmation` writes a
`pending` row and returns `Pause`. The harness emits `handoff_pending`, stops
dispatching, appends the customer's message and the assistant's tool-call message to
working memory, and ends the turn with a reply that asks the customer — the model's own
words when it wrote any alongside the tool call (so the question follows the customer's
language), otherwise a fixed sentence built from the team and reason. The paused call has
no result yet — exactly as Claude Code holds a tool call until permission is given.
`POST /sales-agent/confirm-handoff {session_id, accept, handoff_id?}` resolves the row
(`confirmed` / `declined`) with a conditional update, so two answers cannot both win;
appends the tool result (`{status, team, next}`) to working memory **before** calling the
model, so a provider failure can never leave a dangling tool call; then runs the loop
without a new customer message, so the follow-up comes from the tool result alone. A
`handoff_id` that is no longer the pending one is refused (409).

Before any new turn, `_settled_working_memory` makes the transcript valid: a handoff
still pending is resolved as `declined` and its result appended (the customer moved on);
a pending row whose tool call never reached working memory — the customer disconnected
while the question was on its way — is marked `abandoned`; any other tool call left
without a result gets a "not run" one. Only a confirmation brings a team in; declined and
abandoned rows are bookkeeping and contact nobody.

The three policy skills (`pricing_conversation`, `security_compliance`,
`objection_handling`) are the customer-facing translation of the three Internal
Knowledge documents: behaviour rules, the questions to establish first, and the
documents' approved client-facing wording — no thresholds, discount ranges, approval
workflows, competitor tactics or segmentation tables
([ADR 0003](docs/adr/0003-internal-knowledge-never-enters-customer-context.md)). A test
loads them and asserts the prompt stays free of internal markers.

### The Provider seam — `provider.py`

The only path to a model. `complete(CompletionRequest) -> Iterator[StreamEvent]`
streams `TextDelta` / `ReasoningDelta` events and ends with `Completed(completion)`,
whose `tool_calls` carry the raw JSON arguments the model wrote; `embed(texts)` returns
vectors. `CompletionRequest` carries the wire-shaped `messages` and `tools`,
`max_tokens`, the DeepSeek `thinking` switch, and an optional `tool_choice`. Two
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
| `POST /sales-agent/stream` | runs a turn as SSE: `event: <name>\ndata: <json>\n\n` — `thinking`, `tool_call {call_id, name, arguments}`, `skill_loaded {name}`, `tool_result {name, chars, cached, is_error}`, `hook_blocked {tool, hook}`, `text_delta`, `done`, `error`. Tool output and hook feedback are for the model and never reach the client |
| `GET /api/customers` | sign-in selector |
| `GET /api/metrics?days=N` | `summary()` — turns, errors, avg latency, avg tokens, cache hit rate, tool rounds, tool-cache hits, provider calls per turn; `tool_usage()` — calls per tool |

`done` carries `sources` — the `(title, url)` pairs collected by `source_extraction` — and the UI renders them as links under the reply; `/sales-agent/chat` returns them in `ChatResponse.sources`.
| `GET /` | the chat UI |

The UI (`static/index.html`) is a single page: a sign-in-as-customer selector, a
streamed conversation with a Claude Code-style activity list above each reply (one row
per tool call: skill loaded, result size, cached, or blocked-by-hook), and per-reply
latency / token / cache-hit / tool-round figures. The session id lives in
`localStorage` per customer.

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
| runtime | `handoffs` | one row per proposed handoff: session, customer, team, reason, evidence, `pending` → `confirmed` / `declined` / `abandoned` |
| runtime | `turn_metrics` | one row per turn |

`get_connection()` opens the runtime file as the main database (`WAL`,
`busy_timeout=5000`, `foreign_keys=ON`) and `ATTACH`es the seed file with `mode=ro`.
Unqualified table names resolve to whichever file holds them, so callers never learn
the split and a write to a seed table fails instead of dirtying a tracked file.
`database.py` is the only module that knows which table lives where. The seed is built
with a rollback journal so no `-wal`/`-shm` sidecars appear beside a tracked file.
`SEED_DB_PATH` / `RUNTIME_DB_PATH` override the locations; the test suite points the
runtime at a temp file for the whole run.

## Knowledge retrieval — `app/retrieval/`

### Knowledge graph — `graph.py`, `knowledge_base/knowledge_graph.yaml`

80 nodes, 150 edges in a `networkx.DiGraph`: 16 products, 24 payment methods, 8
compliance standards, 7 geographies, 5 customer types, plus product lines and the old
routing scenarios (kept in the file, unused). Two questions are asked of it:
`related_products(p)` — products one hop away along `integrates_with` / `cross_sell`,
either direction — and `products_for(topic)` — products that point at a compliance
standard (`complies_with`), payment method (`supports_method`), geography
(`available_in`) or customer type (`suitable_for`).

### Entity Linking and Graph Expansion — `linking.py`

The `search_knowledge` tool's `products` and `topics` parameters are enums built from
the graph (`vocabulary()`), so the model can only name entities that exist — that is
the linking step, done by the model. `link()` validates the names, then expands: linked
products plus their one-hop neighbours plus the products each topic points at. When the
model names nothing, `keyword_products()` links products by name and alias from the
question text; the result is marked `fallback` and is never preferred over the model's
own linking ([ADR 0001](docs/adr/0001-model-decides-guardrails-constrain.md)). The
fallback phrase list holds only unambiguous product names — "link", "connect",
"platform", "elements" are absent on purpose, because the fallback narrows the filter
and a false match would exclude the right documents. `filter_expr()` renders the
expanded set as `product in [...] and access_level == "public"` — the public clause is
belt and braces, since only public chunks exist.

### Documents and chunks — `documents.py`, `chunking.py`

`load_public_documents()` reads every `knowledge_base/**/*.md`, keeps those whose header
says `Access Level: public` (18 of 21), maps each to its graph product (`Product:`
header; pricing and security overviews file under `payments`), and records the
product's neighbours, payment methods and compliance standards as metadata. It is the
single implementation of the public-only rule: the index and `get_pricing` both read
through it, and the three Internal Knowledge documents have nothing but their header
checked ([ADR 0003](docs/adr/0003-internal-knowledge-never-enters-customer-context.md)).

`chunk_markdown()` drops the header block, splits the body at `##` / `###` headings,
packs paragraphs, bullets and table rows greedily to ~600 characters, and prefixes each
chunk with `<title> — <heading path>` so a passage read alone still says what it is
about. 18 documents become 177 chunks (average 435 characters). No framework.

### The index — `index.py`, `ingest.py`

Two Milvus Lite collections with identical rows and metadata: `knowledge_dense`
(embedding from `Provider.embed`, COSINE, AUTOINDEX) and `knowledge_sparse` (a BM25
sparse vector Milvus computes from `text`, `SPARSE_INVERTED_INDEX`). They are siblings
because Milvus Lite on Windows fails on a second vector index in one collection
([ADR 0004](docs/adr/0004-hybrid-retrieval-via-sibling-collection.md)). `build_index()`
drops every existing collection when rebuilding (the previous single collection held
internal chunks), embeds in batches through the Provider, and upserts both. A first
search checks that the provider's vector size matches the one the index was built with
and fails with a clear message otherwise.

`KnowledgeIndex.search(question, products, topics, top_k=6)` links and expands, embeds
the question, runs the dense and BM25 legs with the same filter and `3 × top_k`
candidates each, and fuses by reciprocal rank (`1 / (60 + rank)` summed over legs). Each
hit records the rank it had in each leg; `sources` de-duplicates `(title, url)` in hit
order. Because embeddings come through the Provider seam, the test suite builds a real
index from a fixture knowledge base with the fake embedder — whose vectors are
bag-of-words hashes, so texts sharing words are near each other — and asserts on both
legs, fusion, filtering and the absence of the fixture's internal document.

`python -m app.retrieval.ingest` rebuilds `milvus.db/` from scratch with the production
provider (OpenAI embeddings); the directory is tracked so a clean checkout runs.

## Observability — `app/metrics.py`

`TurnRecord` → `turn_metrics`. `init_metrics()` creates the table and adds any column an
older runtime database lacks (`ALTER TABLE … ADD COLUMN`, driven from the schema), so a
`runtime.db` from an earlier version keeps working. `summary(days)` returns turn count, error count,
average latency, average prompt / completion / reasoning tokens, total cache hit and
miss tokens, `cache_hit_rate = hit / (hit + miss)`, tool rounds, tool-cache hits,
provider calls per turn, sub-agent delegations and tokens, and handoffs confirmed and
declined; `tool_usage(days)` counts calls per tool. Each row also keeps the turn's tools, skills and hook outcomes as JSON. Prompt-cache hit rate is a
first-class number because the prefix discipline in ADR 0005 is easy to break by
accident and this is where a break shows first.

## Testing

104 tests, no network, one temp runtime database and one temp Milvus Lite index per run, ~17 s. The app under test
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
| #5 | `ask_customer`, `Stop` guardrails (`anti_placeholder`, `internal_canary`) |
| #9 | prospect discovery and lead capture |
| #10 | Customer Memory and Reflection |
| #11 | attachments, tool-result clearing, compaction with hysteresis |
| #12 | evaluation suite |
| #13 | final documentation pass |
