"""
Test Provider: plays back a script and records every request.

Tests hand it what the model should "say" next — plain text, a full
`Completion` (to control tool calls or usage numbers), or an exception to
raise — then assert on `requests`, the exact `CompletionRequest`s the harness
built. That recorded list is how tests observe things the HTTP response never
shows: prefix stability, what a sub-agent was and wasn't told, which skill body
was loaded.

Embeddings are deterministic unit vectors derived from the text, so retrieval
fixtures can be built without a network.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import replace
from typing import Iterator, Sequence

from app.harness.provider import (
    Completed,
    Completion,
    CompletionRequest,
    ReasoningDelta,
    StreamEvent,
    TextDelta,
    Usage,
)

ScriptItem = str | Completion | BaseException

_DEFAULT_USAGE = Usage(prompt_tokens=200, completion_tokens=20, cache_hit_tokens=0, cache_miss_tokens=200)


class ScriptedProvider:
    def __init__(self, embedding_dim: int = 1536):
        self._script: list[ScriptItem] = []
        self.requests: list[CompletionRequest] = []
        self.embed_requests: list[list[str]] = []
        self._embedding_dim = embedding_dim

    def script(self, *items: ScriptItem) -> "ScriptedProvider":
        """Queue what the next completions return, in order."""
        self._script.extend(items)
        return self

    # ------------------------------------------------------------------
    def complete(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        self.requests.append(request)
        assert self._script, "ScriptedProvider: script exhausted — the harness asked for one more completion than the test scripted"
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        completion = item if isinstance(item, Completion) else Completion(content=item, usage=_DEFAULT_USAGE)
        completion = replace(completion, model=completion.model or request.model)
        # Stream in word-sized pieces so callers exercise real delta handling.
        if completion.reasoning_content:
            for piece in re.findall(r"\S+\s*", completion.reasoning_content):
                yield ReasoningDelta(piece)
        for piece in re.findall(r"\S+\s*", completion.content):
            yield TextDelta(piece)
        yield Completed(completion)

    # ------------------------------------------------------------------
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.embed_requests.append(list(texts))
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        raw = []
        counter = 0
        while len(raw) < self._embedding_dim:
            block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            raw.extend(b / 255.0 - 0.5 for b in block)
            counter += 1
        raw = raw[: self._embedding_dim]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]
