# The prompt prefix is append-only

DeepSeek context caching is a prefix match, and we treat prompt-cache hit rate as a
first-class metric. Every request is therefore built in a fixed order - static system
policy and skill index, tool definitions, the customer block (profile plus customer
memory), then the session's messages - and nothing before the newest message is ever
rewritten: no timestamps or request IDs in the prefix, new memories are appended as
messages rather than re-rendered into the customer block, and compaction is the only
operation allowed to rewrite history, so it runs rarely and in large steps.

This constrains what look like harmless improvements - injecting "today's date",
refreshing the profile mid-session, trimming a message here and there - all of which
silently zero the cache. `prompt_cache_hit_tokens` is recorded per turn so a regression
shows up in metrics rather than in the bill.
