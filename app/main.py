"""
FastAPI transport for the Stripe AI Sales Agent.

The app owns one `Harness` (built at startup from the environment unless a
test installed its own on `app.state.harness` first) and exposes it over a
synchronous chat endpoint and an SSE stream. Everything about a turn lives in
the harness; this module only moves bytes.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.database import get_connection, init_db
from app import database
from app.harness.core import Harness, NothingPending, SessionCustomerMismatch, SessionEnded, TurnEvent, UnknownCustomer, UnknownSession
from app.harness.deepseek import DeepSeekProvider
from app.metrics import init_metrics, summary, tool_usage
from app.schemas import ChatRequest, ChatResponse, ConfirmHandoffRequest, EndSessionRequest, EndSessionResponse

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_metrics()
    if getattr(app.state, "harness", None) is None:
        load_dotenv()  # DEEPSEEK_API_KEY / OPENAI_API_KEY for the production provider
        app.state.harness = Harness.build(provider=DeepSeekProvider.from_env())
    yield
    app.state.harness.close()


app = FastAPI(
    title="Stripe AI Sales Agent",
    description="A customer-facing AI sales agent on a hand-built, Claude Code-style harness.",
    version="0.3.0",
    lifespan=lifespan,
)
app.state.harness = None


def _harness(request: Request) -> Harness:
    return request.app.state.harness


# ---------------------------------------------------------------------------
# Chat UI
# ---------------------------------------------------------------------------
@app.get("/")
def chat_ui():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return {"message": "Stripe AI Sales Agent API", "docs_url": "/docs"}


# ---------------------------------------------------------------------------
# API: customers (sign-in-as selector) — the first choice is to be a new prospect
# ---------------------------------------------------------------------------
NEW_PROSPECT = {"customer_id": None, "customer_name": "New prospect", "industry": None, "annual_payment_volume": None, "prospect": True}


@app.get("/api/customers")
def list_customers():
    rows = get_connection().execute(
        "SELECT customer_id, customer_name, industry, annual_payment_volume "
        "FROM customers ORDER BY customer_name"
    ).fetchall()
    return [NEW_PROSPECT, *({**dict(r), "prospect": False} for r in rows)]


@app.get("/api/leads")
def list_leads(limit: int = 50):
    """What the agent learned from prospects, most recently updated first — for whoever follows up."""
    return database.list_leads(limit)


# ---------------------------------------------------------------------------
# API: chat
# ---------------------------------------------------------------------------
@app.post("/sales-agent/chat", response_model=ChatResponse)
def chat(body: ChatRequest, request: Request):
    """Run one turn and return the finished reply."""
    final: TurnEvent | None = None
    for event in _run(request, body):
        if event.name in ("done", "error"):
            final = event
    if final is None:
        raise HTTPException(status_code=500, detail="the turn produced no result")
    return ChatResponse(**final.data)


def _run(request: Request, body: ChatRequest):
    """Start a turn, translating session-binding refusals into HTTP errors before streaming."""
    events = _harness(request).run_turn(body.session_id, body.customer_id, body.message)
    try:
        first = next(events)
    except UnknownCustomer as exc:
        raise HTTPException(status_code=404, detail=f"unknown customer {exc}") from exc
    except SessionCustomerMismatch as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionEnded as exc:
        raise HTTPException(status_code=409, detail=f"session {exc} has ended; start a new conversation") from exc
    except StopIteration:
        return
    yield first
    yield from events


def _sse(event: TurnEvent) -> str:
    return f"event: {event.name}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


@app.post("/sales-agent/stream")
def chat_stream(body: ChatRequest, request: Request):
    """Run one turn as Server-Sent Events: text_delta* then done (or error)."""
    events = _run(request, body)
    return StreamingResponse(
        (_sse(event) for event in events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.post("/sales-agent/confirm-handoff")
def confirm_handoff(body: ConfirmHandoffRequest, request: Request):
    """The customer answered the pending handoff; the agent picks the conversation up from there (SSE)."""
    pending = database.pending_handoff(body.session_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="no handoff is waiting for confirmation in this session")
    if body.handoff_id is not None and body.handoff_id != pending["id"]:
        raise HTTPException(status_code=409, detail="that proposal is no longer the one waiting; reload the conversation")
    events = _harness(request).resume_turn(body.session_id, body.accept)
    try:
        first = next(events)
    except NothingPending as exc:
        raise HTTPException(status_code=404, detail="no handoff is waiting for confirmation in this session") from exc
    except StopIteration:
        return StreamingResponse(iter(()), media_type="text/event-stream")
    return StreamingResponse(
        (_sse(event) for event in (first, *events)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.post("/sales-agent/end", response_model=EndSessionResponse)
def end_session(body: EndSessionRequest, request: Request):
    """The customer ends the conversation: SessionEnd runs reflection and the session takes no more turns."""
    try:
        return EndSessionResponse(**_harness(request).end_session(body.session_id))
    except UnknownSession as exc:
        raise HTTPException(status_code=404, detail=f"unknown session {exc}") from exc
    except SessionEnded as exc:
        raise HTTPException(status_code=409, detail=f"session {exc} has already ended") from exc


# ---------------------------------------------------------------------------
# API: observability
# ---------------------------------------------------------------------------
@app.get("/api/metrics")
def get_metrics(days: int = 7):
    """Turn volume, latency, tokens per turn, and prompt-cache hit rate."""
    return {"window_days": days, "summary": summary(days), "tool_usage": tool_usage(days)}
