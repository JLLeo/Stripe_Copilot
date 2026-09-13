"""
The Provider seam — the only path from the harness to a model.

Two adapters satisfy it: `DeepSeekProvider` in production and
`ScriptedProvider` in tests. The request and response shapes below are the
whole interface; nothing else in the harness imports an SDK.

`complete()` always streams: it yields text and reasoning deltas as they
arrive and finishes with a `Completed` event carrying the full completion and
its usage. Callers that want the whole answer at once use `drain()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Iterator, Protocol, Sequence


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(**{f.name: getattr(self, f.name) + getattr(other, f.name) for f in fields(Usage)})


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON as the model wrote it; parse with json.loads, never string-match


@dataclass(frozen=True)
class Completion:
    content: str = ""
    reasoning_content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = "stop"
    usage: Usage = field(default_factory=Usage)
    model: str = ""

    def to_message(self) -> dict[str, Any]:
        """The assistant message to append to a conversation, in Chat Completions shape.

        `reasoning_content` is kept: DeepSeek requires it back whenever `tools` are present.
        """
        msg: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.reasoning_content:
            msg["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in self.tool_calls
            ]
        return msg


@dataclass(frozen=True)
class CompletionRequest:
    """One Chat Completions call. `messages` and `tools` are the wire shapes."""

    model: str
    messages: list[dict[str, Any]]
    tools: tuple[dict[str, Any], ...] = ()
    max_tokens: int = 4096
    thinking: str = "enabled"  # DeepSeek: "enabled" | "disabled"
    tool_choice: str | None = None  # None (auto) or "none" to force a text answer


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ReasoningDelta:
    text: str


@dataclass(frozen=True)
class Completed:
    completion: Completion


StreamEvent = TextDelta | ReasoningDelta | Completed


class Provider(Protocol):
    def complete(self, request: CompletionRequest) -> Iterator[StreamEvent]: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def drain(events: Iterator[StreamEvent]) -> tuple[Completion, str]:
    """Consume a completion stream; return the completion and the streamed text."""
    text: list[str] = []
    completion: Completion | None = None
    for event in events:
        if isinstance(event, TextDelta):
            text.append(event.text)
        elif isinstance(event, Completed):
            completion = event.completion
    if completion is None:
        raise RuntimeError("completion stream ended without a Completed event")
    return completion, "".join(text)
