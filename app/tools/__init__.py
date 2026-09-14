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
from app.tools import attachment, catalog, clarify, handoff, knowledge, lead, memory, profile, research


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
    handoff.register(registry)
    clarify.register(registry)
    lead.register(registry)
    memory.register(registry)
    attachment.register(registry, result_cap_chars=result_cap_chars)
    knowledge.register_guardrails(hooks)
    handoff.register_guardrails(hooks)
    clarify.register_guardrails(hooks)
    lead.register_guardrails(hooks)
    memory.register_guardrails(hooks)
    memory.register_reflection(hooks, provider, model=sub_model, thinking=thinking)
