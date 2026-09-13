# Stripe AI Sales Agent

An AI agent that sells Stripe directly to customers: it answers a prospect's or
existing customer's questions from public product knowledge, qualifies their needs,
recommends products, and hands the conversation to a human specialist when policy or
the customer requires one. One bounded context: the agent's harness and the sales
domain it serves.

## Language

### Harness

**Harness**:
The hand-built runtime that composes the model's prompt, runs the model, dispatches
the tool calls it makes, fires hooks around them, and manages the conversation's
context. The harness never decides *what* to do; the model does.
_Avoid_: pipeline, graph, agent loop (as a name for the whole runtime)

**Turn**:
One customer message and everything the harness does until the model's reply is
final: any number of tool calls, hook firings, and skill loads.
_Avoid_: query, request, iteration

**Guardrail**:
A deterministic check that validates or constrains an action the model has already
chosen. A guardrail can block, rewrite, or annotate; it never selects the action.
_Avoid_: rule, filter, classifier, router

**Hook**:
A fixed moment where guardrails attach: when a session starts or ends, before a tool
runs, after it returns, or when the model tries to finish. A hook that blocks returns
feedback to the model instead of failing the turn.
_Avoid_: middleware, interceptor

**Policy**:
A standing rule, written for the model to follow, about what the agent may say or
promise. When a conversation runs into one, the answer is a Handoff, never an
improvisation. Some policies also have a guardrail behind them; most rely on the
model alone.
_Avoid_: guideline, restriction, rule

**Skill**:
A markdown instruction file the model loads into its context on demand when a
conversation calls for it. Skills shape how the model behaves in a situation; they
do not restrict which tools it may use.
_Avoid_: scenario, intent, skill config

**Sub-agent**:
A tool whose implementation is its own bounded model loop with an isolated context.
It returns a brief to the main conversation, never its raw working.
_Avoid_: worker, chain, helper LLM

### Sales

**Customer**:
The person the agent is talking to: an existing Stripe customer with a known
profile, or a Prospect. There is no sales representative in the conversation.
_Avoid_: user, client, account, end user

**Prospect**:
A customer who has no Stripe relationship yet, so nothing is known about them until
they say it. What the agent learns becomes a Lead.
_Avoid_: visitor, anonymous user, guest

**Lead**:
The record the agent captures about a Prospect: who they are, what they need, and how
qualified they are.
_Avoid_: contact, inquiry, signup

**Customer Profile**:
The facts Stripe already holds about a customer: company, stage, business model,
payment volume, products in use. The agent sees only the profile of the customer it
is talking to.
_Avoid_: account, customer data, customer record

**Handoff**:
The agent passing the conversation to a human Team, either because the customer asked
for a person or because a Policy requires one. A handoff always waits for the
customer's confirmation.
_Avoid_: escalation, transfer, routing

**Team**:
One of the seven human specialist groups a Handoff can go to.
_Avoid_: department, queue, escalation team

**Public Knowledge**:
Product documentation the agent may retrieve and quote to a customer.
_Avoid_: docs, knowledge base (when internal material is meant too)

**Internal Knowledge**:
Material written for Stripe staff only. It is never retrievable in a customer
conversation; its guidance reaches the agent only as rules inside a Skill.
_Avoid_: internal docs, playbook (as a general term)

### Memory

**Session**:
One conversation between a customer and the agent, from first message to last.
_Avoid_: chat, thread, conversation (as a noun for the unit)

**Working Memory**:
Everything said and done in the current session, kept in order and only ever
appended to.
_Avoid_: history, context window, transcript

**Compaction**:
Replacing the oldest part of working memory with a summary once the context budget
is reached, while the most recent turns stay verbatim. Done rarely and in large
steps.
_Avoid_: truncation, summarization, sliding window

**Customer Memory**:
Durable facts about a customer that outlive a session: needs, objections,
preferences, commitments, and where they are in the buying process.
_Avoid_: long-term memory, notes, CRM data

**Reflection**:
The end-of-session pass that extracts Customer Memory the agent did not record
during the conversation.
_Avoid_: post-processing, summarization

**Context Budget**:
The share of the model's context window a session may occupy. Pressure against it is
relieved by limiting inputs first, clearing spent tool results second, and compacting
last.
_Avoid_: token limit, max tokens, window size

**Attachment**:
A long customer input kept outside the conversation and read by the agent in pieces
when it needs it, instead of being placed in context whole.
_Avoid_: upload, file, document (for this purpose)

### Retrieval

**Entity Linking**:
The model naming which products and topics a question is about, from the knowledge
graph's own vocabulary, when it asks for a search.
_Avoid_: keyword matching, intent detection

**Graph Expansion**:
Widening a search from the linked entities to their one-hop neighbours in the
knowledge graph, so related products and compliance topics are searched too.
_Avoid_: query expansion, KG traversal

**Brief**:
The short, cited answer a Sub-agent returns to the main conversation in place of its
raw search results.
_Avoid_: summary, report
