"""
Turn metrics — what each turn cost and how the prompt cache did.

One row per turn in the runtime database. Prompt-cache hit rate is a
first-class number here (ADR 0005): a regression in prefix stability should
show up in `/api/metrics` before it shows up in the bill.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import count_handoffs, get_connection

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
    tool_rounds        INTEGER DEFAULT 0,
    tools_json         TEXT DEFAULT '[]',
    skills_json        TEXT DEFAULT '[]',
    hooks_json         TEXT DEFAULT '{}',
    cache_hits         INTEGER DEFAULT 0,
    subagent_calls     INTEGER DEFAULT 0,
    subagent_prompt_tokens     INTEGER DEFAULT 0,
    subagent_completion_tokens INTEGER DEFAULT 0,
    latency_ms         INTEGER DEFAULT 0,
    error              TEXT
)
"""
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_metrics_session ON turn_metrics(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_metrics_created ON turn_metrics(created_at)",
)


def init_metrics() -> None:
    """Create the metrics table, adding any columns an older runtime database lacks."""
    conn = get_connection()
    conn.execute(_SCHEMA)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(turn_metrics)")}
    for name, declaration in _column_declarations():
        if name not in existing:
            conn.execute(f"ALTER TABLE turn_metrics ADD COLUMN {name} {declaration}")
    for stmt in _INDEXES:
        conn.execute(stmt)
    conn.commit()


def _column_declarations() -> list[tuple[str, str]]:
    """(name, type-and-default) for every column in _SCHEMA, so migrations follow the schema."""
    body = _SCHEMA[_SCHEMA.index("(") + 1 : _SCHEMA.rindex(")")]
    out = []
    for line in body.strip().splitlines():
        parts = line.strip().rstrip(",").split(None, 1)
        if len(parts) == 2 and parts[0] != "turn_id":  # the primary key exists in every version
            out.append((parts[0], parts[1]))
    return out


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
    tool_rounds: int = 0
    tools_called: list[str] = field(default_factory=list)
    skills_loaded: list[str] = field(default_factory=list)
    hook_outcomes: dict[str, int] = field(default_factory=dict)  # allowed / denied / replaced / modified / hard_stop
    cache_hits: int = 0
    subagent_calls: int = 0  # delegations to a sub-agent this turn; their tokens are metered apart from the main model
    subagent_prompt_tokens: int = 0
    subagent_completion_tokens: int = 0
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
                cache_hit_tokens, cache_miss_tokens, provider_calls,
                tool_rounds, tools_json, skills_json, hooks_json, cache_hits,
                subagent_calls, subagent_prompt_tokens, subagent_completion_tokens, latency_ms, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.turn_id, record.session_id, record.customer_id,
                datetime.now(timezone.utc).isoformat(), record.model,
                record.prompt_tokens, record.completion_tokens, record.reasoning_tokens,
                record.cache_hit_tokens, record.cache_miss_tokens, record.provider_calls,
                record.tool_rounds, json.dumps(record.tools_called), json.dumps(record.skills_loaded),
                json.dumps(record.hook_outcomes), record.cache_hits,
                record.subagent_calls, record.subagent_prompt_tokens, record.subagent_completion_tokens,
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
            SUM(prompt_tokens + completion_tokens)     AS total_tokens,
            SUM(tool_rounds)                           AS tool_rounds,
            SUM(cache_hits)                            AS tool_cache_hits,
            AVG(provider_calls)                        AS avg_provider_calls,
            SUM(subagent_calls)                        AS subagent_calls,
            SUM(subagent_prompt_tokens + subagent_completion_tokens) AS subagent_tokens
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
        "tool_rounds": row["tool_rounds"] or 0,
        "tool_cache_hits": row["tool_cache_hits"] or 0,
        "avg_provider_calls": round(row["avg_provider_calls"] or 0.0, 2),
        "subagent_calls": row["subagent_calls"] or 0,
        "subagent_tokens": row["subagent_tokens"] or 0,
        "handoffs_confirmed": count_handoffs(since, "confirmed"),
        "handoffs_declined": count_handoffs(since, "declined"),
    }


def tool_usage(days: int = 7) -> dict[str, int]:
    """How often each tool was called in the window, most used first."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    counts: dict[str, int] = {}
    for (raw,) in get_connection().execute(
        "SELECT tools_json FROM turn_metrics WHERE created_at >= ?", (since,)
    ).fetchall():
        for name in json.loads(raw or "[]"):
            counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
