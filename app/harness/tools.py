"""
Tools — plain functions with a JSON schema, in a registry the model sees.

A tool is `(name, description, parameters schema, function)`. The registry
renders the tool definitions the model receives, in registration order so the
prefix stays stable (ADR 0005), and dispatches a call: parse the arguments,
check them against the schema's `required` list, run the function, and return
its result as text the model can read.

Tools never decide anything on the model's behalf and never gate each other;
skills recommend tools, they do not restrict them (ADR 0001).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# What a tool receives and returns
# ---------------------------------------------------------------------------
EventSink = Callable[[str, dict[str, Any]], None]  # (event name, payload) -> None


def _drop_event(name: str, data: dict[str, Any]) -> None:
    """Default event sink: a tool run outside a turn has nowhere to report progress."""


@dataclass(frozen=True)
class ToolContext:
    """What a tool may know about the conversation it runs in, and how it reports progress."""

    session_id: str
    customer_id: str | None
    emit: EventSink = _drop_event  # progress events for the customer's client, forwarded as they happen
    turn_id: str = ""  # the turn (or SessionEnd pass) the call belongs to; memory rows record it as their source


@dataclass(frozen=True)
class EndTurn:
    """A tool result that also ends the turn: the customer must answer before the model goes on.

    Placed on `ToolResult.meta["end_turn"]`. The tool's result is written like any other,
    so working memory stays a valid sequence; the harness stops dispatching, emits `event` with
    `data`, and makes `reply` what the customer sees.
    """

    event: str
    data: dict[str, Any]
    reply: str


@dataclass(frozen=True)
class ToolResult:
    content: str  # what the model reads; JSON for structured results
    is_error: bool = False
    meta: dict[str, Any] = field(default_factory=dict)  # for events and metrics, never sent to the model

    @classmethod
    def from_payload(cls, payload: Any, **meta: Any) -> "ToolResult":
        # Compact JSON: tool results live in the cached prefix, so every character is paid for on each turn.
        return cls(content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")), meta=meta)

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        return cls(content=message, is_error=True)


ToolFunction = Callable[[ToolContext, dict[str, Any]], ToolResult]


# ---------------------------------------------------------------------------
# Tools and the registry
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the arguments object
    run: ToolFunction
    cacheable: bool = True  # identical calls within a session may be served from the tool cache

    def definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} registered twice")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def definitions(self) -> tuple[dict[str, Any], ...]:
        """Wire-shaped definitions in registration order — part of the cached prefix."""
        return tuple(t.definition() for t in self._tools.values())

    def parse_arguments(self, tool: Tool, raw: str) -> dict[str, Any] | str:
        """Arguments as a dict, or a feedback string explaining what was wrong."""
        try:
            args = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as exc:
            return f"The arguments for {tool.name} were not valid JSON ({exc.msg}). Send a JSON object."
        if not isinstance(args, dict):
            return f"The arguments for {tool.name} must be a JSON object."
        missing = [k for k in tool.parameters.get("required", ()) if k not in args]
        if missing:
            return f"{tool.name} is missing required argument(s): {', '.join(missing)}."
        unknown = [k for k in args if k not in tool.parameters.get("properties", {})]
        if unknown:
            return f"{tool.name} does not accept: {', '.join(unknown)}."
        return args

    def call(self, tool: Tool, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        try:
            return tool.run(ctx, args)
        except Exception as exc:  # noqa: BLE001 — a failing tool is feedback, not a crash
            return ToolResult.error(f"{tool.name} failed: {type(exc).__name__}: {exc}")

    def dispatch(self, name: str, raw_arguments: str, ctx: ToolContext) -> ToolResult:
        """Look up, parse and call in one step; every failure is an error result the model can read."""
        tool = self.get(name)
        if tool is None:
            return ToolResult.error(f"No tool named {name!r} here. Available: {', '.join(self.names())}.")
        parsed = self.parse_arguments(tool, raw_arguments)
        if isinstance(parsed, str):
            return ToolResult.error(parsed)
        return self.call(tool, ctx, parsed)
