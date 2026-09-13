"""Request and response shapes for the chat endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    customer_id: str | None = None  # None: a prospect with no Stripe account
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    session_id: str
    turn_id: str
    reply: str
    usage: dict[str, int] | None = None
    latency_ms: int | None = None
    tool_rounds: int | None = None
    sources: list[dict[str, str]] = Field(default_factory=list)
    error: str | None = None
