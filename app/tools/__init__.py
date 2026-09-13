"""
The agent's tools — what the model can look up while talking to a customer.

Each module defines plain functions and registers them as `Tool`s. Nothing
here decides for the model; these are facts on request (ADR 0001).
"""

from __future__ import annotations

from app.harness.tools import ToolRegistry
from app.tools import catalog, profile


def register_all(registry: ToolRegistry) -> None:
    """Register every tool, in the order the model sees them."""
    profile.register(registry)
    catalog.register(registry)
