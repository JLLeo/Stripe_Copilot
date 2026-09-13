# Hand-built harness on DeepSeek; no agent SDK

The harness is the deliverable of this project, so we build the agent loop, hook
points, context management, sub-agents, and memory by hand, modelled on Claude Code's
design, rather than adopting a framework that would own them (Claude Agent SDK, OpenAI
Agents SDK, LangChain - the last of which we removed entirely, including its text
splitter). The model behind the loop is DeepSeek through its OpenAI-compatible Chat
Completions API: `deepseek-v4-pro` for the main conversation, `deepseek-flash` for
sub-agents, compaction, reflection, and evaluation judges. Embeddings stay on OpenAI's
`text-embedding-3-small`, because DeepSeek offers no embedding endpoint and the
existing Milvus index is 1536-dimensional.

## Considered Options

- **Anthropic SDK with a hand-built loop** - the closest match to Claude Code's
  primitives, but no Anthropic credentials were available.
- **Claude Agent SDK** - Claude Code as a library; maximally faithful, but it owns the
  loop we want to demonstrate, and its built-in tools are filesystem-oriented.
- **Stay on OpenAI `gpt-4o-mini`** - zero migration, but DeepSeek exposes prompt-cache
  hit counts per request and reasoning at low cost, both of which this design leans on.

## Consequences

- Two providers in `.env` (DeepSeek for chat, OpenAI for embeddings), one client
  library.
- No Responses API: the loop is written against Chat Completions, and V4's
  `reasoning_content` must be handled per DeepSeek's rules inside tool-call rounds.
