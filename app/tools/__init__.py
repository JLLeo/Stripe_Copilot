"""
The agent's tools — what the model can look up while talking to a customer.

Each module defines plain functions and registers them as `Tool`s. Nothing
here decides for the model; these are facts on request (ADR 0001).
"""

from __future__ import annotations

from app.harness.hooks import HookRegistry
from app.harness.provider import Provider
from app.harness.tools import ToolRegistry
from app.retrieval.index import KnowledgeIndex
from app.tools import catalog, knowledge, profile, research


def register_all(
    registry: ToolRegistry,
    hooks: HookRegistry,
    index: KnowledgeIndex,
    *,
    provider: Provider,
    sub_model: str,
    subagent_max_rounds: int,
    thinking: str,
    result_cap_chars: int,
) -> None:
    """Register every tool, in the order the model sees them, and the guardrails they bring."""
    profile.register(registry)
    catalog.register(registry)
    knowledge.register(registry, index)
    research.register(
        registry, provider, index,
        model=sub_model, max_rounds=subagent_max_rounds, thinking=thinking, result_cap_chars=result_cap_chars,
    )
    knowledge.register_guardrails(hooks)
