"""
The agent's tools — what the model can look up while talking to a customer.

Each module defines plain functions and registers them as `Tool`s. Nothing
here decides for the model; these are facts on request (ADR 0001).
"""

from __future__ import annotations

from app.harness.hooks import HookRegistry
from app.harness.tools import ToolRegistry
from app.retrieval.index import KnowledgeIndex
from app.tools import catalog, knowledge, profile


def register_all(registry: ToolRegistry, hooks: HookRegistry, index: KnowledgeIndex) -> None:
    """Register every tool, in the order the model sees them, and the guardrails they bring."""
    profile.register(registry)
    catalog.register(registry)
    knowledge.register(registry, index)
    knowledge.register_guardrails(hooks)
