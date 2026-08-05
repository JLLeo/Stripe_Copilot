"""
Database helpers — SQLite connection, WAL mode, session memory table.

Reuses: data/stripe_sales_copilot.db (5 existing tables)
Adds:   session_memory table for conversation persistence
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stripe_sales_copilot.db"

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
_connection: sqlite3.Connection | None = None


def get_connection() -> sqlite3.Connection:
    """Return (and cache) a WAL-mode SQLite connection."""
    global _connection
    if _connection is None:
        _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA journal_mode=WAL")
        _connection.execute("PRAGMA busy_timeout=5000")
        _connection.execute("PRAGMA foreign_keys=ON")
    return _connection


def init_db() -> None:
    """Create session_memory table if it doesn't exist. Call at app startup."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_memory (
            session_id   TEXT PRIMARY KEY,
            customer_id  TEXT,
            turns_json   TEXT DEFAULT '[]',
            summary      TEXT DEFAULT '',
            updated_at   TEXT
        )
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Session memory operations
# ---------------------------------------------------------------------------
def load_session(session_id: str) -> dict[str, Any]:
    """Load session state: {turns, summary, customer_id} or empty defaults."""
    conn = get_connection()
    row = conn.execute(
        "SELECT turns_json, summary, customer_id FROM session_memory WHERE session_id = ?",
        (session_id,),
    ).fetchone()

    if row is None:
        return {"turns": [], "summary": "", "customer_id": None}

    return {
        "turns": json.loads(row["turns_json"]),
        "summary": row["summary"] or "",
        "customer_id": row["customer_id"],
    }


def save_session(
    session_id: str,
    turns: list[dict],
    summary: str = "",
    customer_id: str | None = None,
) -> None:
    """Upsert session state to SQLite."""
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    cid = customer_id if customer_id else None  # empty string -> NULL
    conn.execute(
        """
        INSERT INTO session_memory (session_id, customer_id, turns_json, summary, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            customer_id = excluded.customer_id,
            turns_json = excluded.turns_json,
            summary = excluded.summary,
            updated_at = excluded.updated_at
        """,
        (session_id, cid, json.dumps(turns, ensure_ascii=False), summary, now),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Customer lookup (reads from existing customers table)
# ---------------------------------------------------------------------------
def get_customer(customer_id: str) -> dict[str, Any] | None:
    """Return customer profile from customers table, or None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    return dict(row) if row else None


def get_customer_product_usage(customer_id: str) -> list[dict[str, Any]]:
    """Return products a customer currently uses."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT cpu.*, sp.product_name, sp.product_group
        FROM customer_product_usage cpu
        JOIN stripe_products sp ON cpu.product_id = sp.product_id
        WHERE cpu.customer_id = ? AND cpu.usage_status = 'active'
        """,
        (customer_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_active_policies(product_area: str | None = None) -> list[dict[str, Any]]:
    """Return active sales policies, optionally filtered by area (case-insensitive)."""
    conn = get_connection()
    if product_area:
        rows = conn.execute(
            """
            SELECT * FROM sales_policy_updates
            WHERE is_active = 1 AND LOWER(policy_area) = LOWER(?)
            ORDER BY effective_start_date DESC
            """,
            (product_area,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM sales_policy_updates
            WHERE is_active = 1
            ORDER BY policy_area, effective_start_date DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def log_interaction(
    interaction_id: str,
    customer_id: str,
    sales_rep_id: str,
    channel: str,
    customer_question: str,
    detected_intent: str,
    mentioned_products: str,
    customer_pain_points: str,
    follow_up_action: str,
) -> None:
    """Write an interaction record to sales_interactions table."""
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO sales_interactions
            (interaction_id, customer_id, sales_rep_id, interaction_date, channel,
             customer_question, detected_intent, mentioned_products,
             customer_pain_points, follow_up_action, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            interaction_id, customer_id, sales_rep_id, now, channel,
            customer_question, detected_intent, mentioned_products,
            customer_pain_points, follow_up_action, now,
        ),
    )
    conn.commit()
