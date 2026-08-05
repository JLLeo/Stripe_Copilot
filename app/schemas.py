from pydantic import BaseModel
from typing import Optional, List


class SalesAgentRequest(BaseModel):
    sales_rep_id: str
    customer_id: Optional[str] = None
    session_id: str
    message: str


class SalesAgentResponse(BaseModel):
    intent: str
    recommended_stripe_products: List[str]
    internal_answer: str
    client_ready_response: str
    sources: List[str]
    need_escalation: bool
    escalation_team: Optional[str] = None
    confidence: float