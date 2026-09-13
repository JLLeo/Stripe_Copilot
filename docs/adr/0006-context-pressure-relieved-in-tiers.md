# Context pressure is relieved in tiers, compaction last

Long customer inputs and bulky retrieval results can make the most recent turns alone
exceed the context budget, which would force a compaction on every turn and break the
cached prefix each time (ADR 0005). So compaction is the last resort, not the first:

1. **Limit at the source.** A single tool result is capped (about 1.5K tokens), a turn's
   tool results are capped in total (about 6K), heavy research goes through the
   sub-agent so only a brief enters the conversation, and a customer message over about
   2K tokens is stored as an attachment the model reads on demand with
   `read_attachment(id, offset, limit)` instead of being placed in context whole.
2. **Clear before summarising.** When pressure builds, tool results the model has already
   answered from are replaced by one-line stubs - deterministic and free.
3. **Compact with hysteresis.** Compaction triggers at a high-water mark (about 75% of the
   budget) and compacts down to a low-water mark (about 40%), keeping a token-budgeted
   recent window verbatim rather than a fixed number of turns, and maintaining one
   rolling summary that never grows past a fixed size.

The thresholds are tunable and live in one configuration object. The alternative -
compaction alone - is simpler but degrades exactly in the conversations where a sales
agent is doing its most valuable work.
