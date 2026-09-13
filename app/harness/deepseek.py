"""
Production Provider: DeepSeek for chat, OpenAI for embeddings.

DeepSeek speaks the OpenAI-compatible Chat Completions API, so both halves use
the `openai` client library with different base URLs and keys. DeepSeek has no
embedding endpoint, and the Milvus index is built on `text-embedding-3-small`,
so embeddings stay on OpenAI (ADR 0002).

DeepSeek specifics handled here:
- thinking mode is toggled with `extra_body={"thinking": {"type": ...}}`;
- reasoning arrives as `delta.reasoning_content` and is surfaced as
  `ReasoningDelta` events, then kept on the completion so the harness can
  store it and pass it back — required whenever `tools` are present;
- usage on the final stream chunk carries `prompt_cache_hit_tokens` /
  `prompt_cache_miss_tokens`, our prompt-cache metric.

Transient failures (429, 5xx, connection errors) are retried by the client
library itself (`max_retries`); anything else propagates to the harness.
"""

from __future__ import annotations

import os
from typing import Any, Iterator, Sequence

from openai import OpenAI

from app.harness.provider import (
    Completed,
    Completion,
    CompletionRequest,
    ReasoningDelta,
    StreamEvent,
    TextDelta,
    ToolCall,
    Usage,
)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


class DeepSeekProvider:
    def __init__(self, chat_client: Any, embed_client: Any, embedding_model: str = DEFAULT_EMBEDDING_MODEL):
        self._chat = chat_client
        self._embed = embed_client
        self._embedding_model = embedding_model

    @classmethod
    def from_env(cls, max_retries: int = 3) -> "DeepSeekProvider":
        return cls(
            chat_client=OpenAI(
                api_key=os.environ["DEEPSEEK_API_KEY"],
                base_url=os.environ.get("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL),
                max_retries=max_retries,
            ),
            embed_client=OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=max_retries),
            embedding_model=os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        )

    # ------------------------------------------------------------------
    def complete(self, request: CompletionRequest) -> Iterator[StreamEvent]:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "extra_body": {"thinking": {"type": request.thinking}},
        }
        if request.tools:
            kwargs["tools"] = list(request.tools)
            if request.tool_choice:
                kwargs["tool_choice"] = request.tool_choice

        text: list[str] = []
        reasoning: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        finish_reason = "stop"
        usage = Usage()
        model = request.model

        for chunk in self._chat.chat.completions.create(**kwargs):
            if getattr(chunk, "model", None):
                model = chunk.model
            if getattr(chunk, "usage", None):
                usage = _usage_from(chunk.usage)
            for choice in chunk.choices or ():
                delta = choice.delta
                if getattr(delta, "reasoning_content", None):
                    reasoning.append(delta.reasoning_content)
                    yield ReasoningDelta(delta.reasoning_content)
                if getattr(delta, "content", None):
                    text.append(delta.content)
                    yield TextDelta(delta.content)
                for tc in getattr(delta, "tool_calls", None) or ():
                    slot = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            slot["arguments"] += fn.arguments
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

        yield Completed(Completion(
            content="".join(text),
            reasoning_content="".join(reasoning) or None,
            tool_calls=tuple(ToolCall(**calls[i]) for i in sorted(calls)),
            finish_reason=finish_reason,
            usage=usage,
            model=model,
        ))

    # ------------------------------------------------------------------
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = self._embed.embeddings.create(model=self._embedding_model, input=list(texts))
        return [item.embedding for item in sorted(response.data, key=lambda d: d.index)]


def _usage_from(raw: Any) -> Usage:
    details = getattr(raw, "completion_tokens_details", None)
    return Usage(
        prompt_tokens=getattr(raw, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(raw, "completion_tokens", 0) or 0,
        reasoning_tokens=(getattr(details, "reasoning_tokens", 0) or 0) if details else 0,
        cache_hit_tokens=getattr(raw, "prompt_cache_hit_tokens", 0) or 0,
        cache_miss_tokens=getattr(raw, "prompt_cache_miss_tokens", 0) or 0,
    )
