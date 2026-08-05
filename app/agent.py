"""
Stripe Sales Agent — LangGraph ReAct Loop
==========================================
Thin entry point over graph.py.
Signature compatible with existing SalesAgentRequest / SalesAgentResponse schemas.
"""

from __future__ import annotations

from app.graph import run_agent
from app.schemas import SalesAgentRequest


def run_sales_agent(request: SalesAgentRequest) -> dict:
    """
    KG + Milvus RAG pipeline wrapped in a LangGraph ReAct Agent Loop.

    Flow:
      1. Intent classification (keyword + LLM fallback)
      2. Skill selection (12 scenario-specific configs)
      3. ReAct loop: THINK -> ACT -> OBSERVE (max N iterations)
      4. SYNTH: LLM generates internal + client responses
      5. Escalation gating with evidence checks
      6. Session persistence + logging
    """
    return run_agent(
        query=request.message,
        sales_rep_id=request.sales_rep_id,
        customer_id=request.customer_id or "",
        session_id=request.session_id,
    )
