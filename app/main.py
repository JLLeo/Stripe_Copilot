from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import tool_cache
from app.agent import run_sales_agent
from app.database import get_connection, init_db
from app.graph import stream_agent
from app.metrics import init_metrics, intent_breakdown, summary, tool_usage
from app.schemas import SalesAgentRequest, SalesAgentResponse

# ---------------------------------------------------------------------------
# Static files directory
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_metrics()
    yield


app = FastAPI(
    title="Stripe Sales Copilot",
    description="AI-powered sales enablement agent with KG-enhanced RAG retrieval.",
    version="0.2.0",
    lifespan=lifespan,
)

# Mount static files (CSS/JS if needed later)
if (STATIC_DIR).exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Chat UI
# ---------------------------------------------------------------------------
@app.get("/")
def chat_ui():
    """Serve the single-page chat interface."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return {"message": "Stripe Sales Copilot API", "docs_url": "/docs"}


# ---------------------------------------------------------------------------
# API: Customer list
# ---------------------------------------------------------------------------
@app.get("/api/customers")
def list_customers():
    """Return all customers for the UI dropdown."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT customer_id, customer_name, industry, annual_payment_volume "
        "FROM customers ORDER BY customer_name"
    ).fetchall()
    return [
        {
            "customer_id": r["customer_id"],
            "customer_name": r["customer_name"],
            "industry": r["industry"],
            "annual_payment_volume": r["annual_payment_volume"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# API: Chat (sync — existing)
# ---------------------------------------------------------------------------
@app.post("/sales-agent/chat", response_model=SalesAgentResponse)
def chat(request: SalesAgentRequest):
    result = run_sales_agent(request)
    return result


# ---------------------------------------------------------------------------
# API: Chat (streaming — SSE)
# ---------------------------------------------------------------------------
@app.post("/sales-agent/stream")
async def chat_stream(request: SalesAgentRequest):
    """Stream agent pipeline stages as Server-Sent Events."""
    generator = stream_agent(
        query=request.message,
        sales_rep_id=request.sales_rep_id,
        customer_id=request.customer_id or "",
        session_id=request.session_id,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# API: Confirm escalation (mock human handoff)
# ---------------------------------------------------------------------------
@app.post("/sales-agent/confirm-escalation")
def confirm_escalation(request: SalesAgentRequest):
    """Mock: confirm escalation and return a 'connected to human' message."""
    return {
        "message": (
            f"You are now connected to a {request.message} representative. "
            "They have received the conversation summary and will take over from here. "
            "Thank you for using Stripe Sales Copilot."
        ),
        "status": "escalated",
        "session_id": request.session_id,
    }


# ---------------------------------------------------------------------------
# API: Observability
# ---------------------------------------------------------------------------
@app.get("/api/metrics")
def get_metrics(days: int = 7):
    """Aggregate agent metrics: latency, tokens, cache efficiency, error rate."""
    return {
        "window_days": days,
        "summary": summary(days),
        "by_intent": intent_breakdown(days),
        "tool_usage": tool_usage(days),
        "tool_cache": tool_cache.stats(),
    }
