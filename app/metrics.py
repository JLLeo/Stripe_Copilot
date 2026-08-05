"""
Turn Metrics — structured observability for the agent pipeline.

Records one row per conversation turn: intent path, tools used, LLM calls,
token consumption, per-stage latency, cache efficiency, and errors.

Answers questions the logs alone cannot:
  - How often does intent classification fall back to the LLM?
  - Which tools are slowest?
  - What is the tool cache hit rate?
  - How many ReAct iterations does a typical query need?
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from app.database import get_connection


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS turn_metrics (
    turn_id           TEXT PRIMARY KEY,
    session_id        TEXT NOT NULL,
    customer_id       TEXT,
    sales_rep_id      TEXT,
    created_at        TEXT NOT NULL,

    query             TEXT,
    intent            TEXT,
    intent_method     TEXT,      -- keyword | llm | keyword+context
    intent_confidence REAL,

    tools_called      TEXT,      -- JSON array
    tool_calls        INTEGER,
    cache_hits        INTEGER,
    iterations        INTEGER,
    llm_calls         INTEGER,
    tokens_in         INTEGER,
    tokens_out        INTEGER,

    escalated         INTEGER,   -- 0/1
    escalation_team   TEXT,

    latency_total_ms  REAL,
    latency_stages    TEXT,      -- JSON {stage: ms}

    error             TEXT
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_metrics_session ON turn_metrics(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_metrics_intent  ON turn_metrics(intent)",
    "CREATE INDEX IF NOT EXISTS idx_metrics_created ON turn_metrics(created_at)",
]


def init_metrics() -> None:
    """Create the metrics table. Call once at app startup."""
    conn = get_connection()
    conn.execute(_SCHEMA)
    for stmt in _INDEXES:
        conn.execute(stmt)
    conn.commit()


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------
@dataclass
class TurnMetrics:
    """Mutable collector, filled in as the pipeline runs."""

    session_id: str
    customer_id: str = ""
    sales_rep_id: str = ""
    query: str = ""

    turn_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    intent: str = ""
    intent_method: str = ""
    intent_confidence: float = 0.0

    tools_called: list[str] = field(default_factory=list)
    cache_hits: int = 0
    iterations: int = 0
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    escalated: bool = False
    escalation_team: str = ""

    latency_stages: dict[str, float] = field(default_factory=dict)
    error: str = ""

    _start: float = field(default_factory=time.perf_counter, repr=False)
    _stage_start: float = field(default_factory=time.perf_counter, repr=False)

    # -- recording -------------------------------------------------------
    def mark_stage(self, name: str) -> None:
        """Record elapsed time since the previous mark under `name`."""
        now = time.perf_counter()
        self.latency_stages[name] = round((now - self._stage_start) * 1000, 1)
        self._stage_start = now

    def record_tool(self, tool_name: str, cache_hit: bool = False) -> None:
        self.tools_called.append(tool_name)
        if cache_hit:
            self.cache_hits += 1

    def record_llm(self, response=None) -> None:
        """Count an LLM call and accumulate token usage when available."""
        self.llm_calls += 1
        usage = getattr(response, "usage", None) if response else None
        if usage:
            self.tokens_in += getattr(usage, "prompt_tokens", 0) or 0
            self.tokens_out += getattr(usage, "completion_tokens", 0) or 0

    @property
    def latency_total_ms(self) -> float:
        return round((time.perf_counter() - self._start) * 1000, 1)

    @property
    def unique_tools(self) -> list[str]:
        return list(dict.fromkeys(self.tools_called))

    # -- persistence -----------------------------------------------------
    def save(self) -> None:
        """Write this turn to SQLite. Never raises — metrics are best-effort."""
        try:
            conn = get_connection()
            conn.execute(
                """
                INSERT OR REPLACE INTO turn_metrics (
                    turn_id, session_id, customer_id, sales_rep_id, created_at,
                    query, intent, intent_method, intent_confidence,
                    tools_called, tool_calls, cache_hits, iterations,
                    llm_calls, tokens_in, tokens_out,
                    escalated, escalation_team,
                    latency_total_ms, latency_stages, error
                ) VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?, ?,?, ?,?,?)
                """,
                (
                    self.turn_id, self.session_id, self.customer_id or None,
                    self.sales_rep_id or None, self.created_at,
                    self.query[:2000], self.intent, self.intent_method,
                    self.intent_confidence,
                    json.dumps(self.tools_called), len(self.tools_called),
                    self.cache_hits, self.iterations,
                    self.llm_calls, self.tokens_in, self.tokens_out,
                    1 if self.escalated else 0, self.escalation_team or None,
                    self.latency_total_ms, json.dumps(self.latency_stages),
                    self.error or None,
                ),
            )
            conn.commit()
        except Exception:
            pass  # observability must never break the request

    def to_dict(self) -> dict:
        d = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        d["latency_total_ms"] = self.latency_total_ms
        d["tool_calls"] = len(self.tools_called)
        return d


# ---------------------------------------------------------------------------
# Aggregate queries
# ---------------------------------------------------------------------------
def summary(limit_days: int = 7) -> dict:
    """Aggregate stats over recent turns."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                COUNT(*)                     AS turns,
                AVG(latency_total_ms)        AS avg_latency_ms,
                AVG(iterations)              AS avg_iterations,
                AVG(tool_calls)              AS avg_tool_calls,
                SUM(cache_hits)              AS cache_hits,
                SUM(tool_calls)              AS total_tool_calls,
                SUM(llm_calls)               AS llm_calls,
                SUM(tokens_in)               AS tokens_in,
                SUM(tokens_out)              AS tokens_out,
                SUM(escalated)               AS escalations,
                SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors
            FROM turn_metrics
            WHERE created_at >= datetime('now', ?)
            """,
            (f"-{limit_days} days",),
        ).fetchone()
    except Exception:
        return {}

    if row is None or not row["turns"]:
        return {"turns": 0}

    total_tools = row["total_tool_calls"] or 0
    return {
        "turns": row["turns"],
        "avg_latency_ms": round(row["avg_latency_ms"] or 0, 1),
        "avg_iterations": round(row["avg_iterations"] or 0, 2),
        "avg_tool_calls": round(row["avg_tool_calls"] or 0, 2),
        "cache_hit_rate": round((row["cache_hits"] or 0) / total_tools, 3) if total_tools else 0.0,
        "llm_calls": row["llm_calls"] or 0,
        "tokens_in": row["tokens_in"] or 0,
        "tokens_out": row["tokens_out"] or 0,
        "escalation_rate": round((row["escalations"] or 0) / row["turns"], 3),
        "error_rate": round((row["errors"] or 0) / row["turns"], 3),
    }


def intent_breakdown(limit_days: int = 7) -> list[dict]:
    """Per-intent counts, latency, and classification method split."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                intent,
                COUNT(*)              AS turns,
                AVG(latency_total_ms) AS avg_latency_ms,
                AVG(iterations)       AS avg_iterations,
                SUM(escalated)        AS escalations,
                SUM(CASE WHEN intent_method LIKE 'keyword%' THEN 1 ELSE 0 END) AS via_keyword,
                SUM(CASE WHEN intent_method = 'llm' THEN 1 ELSE 0 END)         AS via_llm
            FROM turn_metrics
            WHERE created_at >= datetime('now', ?)
            GROUP BY intent
            ORDER BY turns DESC
            """,
            (f"-{limit_days} days",),
        ).fetchall()
    except Exception:
        return []

    return [
        {
            "intent": r["intent"],
            "turns": r["turns"],
            "avg_latency_ms": round(r["avg_latency_ms"] or 0, 1),
            "avg_iterations": round(r["avg_iterations"] or 0, 2),
            "escalations": r["escalations"] or 0,
            "via_keyword": r["via_keyword"] or 0,
            "via_llm": r["via_llm"] or 0,
        }
        for r in rows
    ]


def tool_usage(limit_days: int = 7) -> list[dict]:
    """How often each tool is called (expanded from the JSON array column)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT tools_called FROM turn_metrics WHERE created_at >= datetime('now', ?)",
            (f"-{limit_days} days",),
        ).fetchall()
    except Exception:
        return []

    counts: dict[str, int] = {}
    for r in rows:
        try:
            for name in json.loads(r["tools_called"] or "[]"):
                counts[name] = counts.get(name, 0) + 1
        except json.JSONDecodeError:
            continue

    return [
        {"tool": name, "calls": n}
        for name, n in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
