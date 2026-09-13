"""
Turn metrics — what each turn cost and how the prompt cache did.

One row per turn in the runtime database. Prompt-cache hit rate is a
first-class number here (ADR 0005): a regression in prefix stability should
show up in `/api/metrics` before it shows up in the bill.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import get_connection

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS turn_metrics (
    turn_id            TEXT PRIMARY KEY,
    session_id         TEXT NOT NULL,
    customer_id        TEXT,
    created_at         TEXT NOT NULL,
    model              TEXT,
    prompt_tokens      INTEGER DEFAULT 0,
    completion_tokens  INTEGER DEFAULT 0,
    reasoning_tokens   INTEGER DEFAULT 0,
    cache_hit_tokens   INTEGER DEFAULT 0,
    cache_miss_tokens  INTEGER DEFAULT 0,
    provider_calls     INTEGER DEFAULT 0,
    latency_ms         INTEGER DEFAULT 0,
    error              TEXT
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_metrics_session ON turn_metrics(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_metrics_created ON turn_metrics(created_at)",
)


def init_metrics() -> None:
    """Create the metrics table. Call once at app startup."""
    conn = get_connection()
    conn.execute(_SCHEMA)
    for stmt in _INDEXES:
        conn.execute(stmt)
    conn.commit()


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TurnRecord:
    turn_id: str
    session_id: str
    customer_id: str | None
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    provider_calls: int = 0
    latency_ms: int = 0
    error: str | None = None


def record_turn(record: TurnRecord) -> None:
    """Persist one turn. Never raises — metrics are best-effort."""
    try:
        conn = get_connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO turn_metrics (
                turn_id, session_id, customer_id, created_at, model,
                prompt_tokens, completion_tokens, reasoning_tokens,
                cache_hit_tokens, cache_miss_tokens, provider_calls, latency_ms, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.turn_id, record.session_id, record.customer_id,
                datetime.now(timezone.utc).isoformat(), record.model,
                record.prompt_tokens, record.completion_tokens, record.reasoning_tokens,
                record.cache_hit_tokens, record.cache_miss_tokens, record.provider_calls,
                record.latency_ms, record.error,
            ),
        )
        conn.commit()
    except Exception:  # noqa: BLE001 — observability must not break a turn
        log.warning("turn %s not recorded", record.turn_id, exc_info=True)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def summary(days: int = 7) -> dict[str, Any]:
    """Aggregate over the last `days`: volume, latency, tokens, cache hit rate, errors."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    row = get_connection().execute(
        """
        SELECT
            COUNT(*)                                   AS turns,
            SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors,
            AVG(latency_ms)                            AS avg_latency_ms,
            AVG(prompt_tokens)                         AS avg_prompt_tokens,
            AVG(completion_tokens)                     AS avg_completion_tokens,
            AVG(reasoning_tokens)                      AS avg_reasoning_tokens,
            SUM(cache_hit_tokens)                      AS cache_hit_tokens,
            SUM(cache_miss_tokens)                     AS cache_miss_tokens,
            SUM(prompt_tokens + completion_tokens)     AS total_tokens
        FROM turn_metrics
        WHERE created_at >= ?
        """,
        (since,),
    ).fetchone()
    hit = row["cache_hit_tokens"] or 0
    miss = row["cache_miss_tokens"] or 0
    return {
        "turns": row["turns"] or 0,
        "errors": row["errors"] or 0,
        "avg_latency_ms": round(row["avg_latency_ms"] or 0.0, 1),
        "avg_prompt_tokens": round(row["avg_prompt_tokens"] or 0.0, 1),
        "avg_completion_tokens": round(row["avg_completion_tokens"] or 0.0, 1),
        "avg_reasoning_tokens": round(row["avg_reasoning_tokens"] or 0.0, 1),
        "cache_hit_tokens": hit,
        "cache_miss_tokens": miss,
        "cache_hit_rate": (hit / (hit + miss)) if (hit + miss) else 0.0,
        "total_tokens": row["total_tokens"] or 0,
    }
