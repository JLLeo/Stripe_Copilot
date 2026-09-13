"""
Database access — one connection over two SQLite files.

Seed database   (tracked, read-only)   data/seed.db
    customers, stripe_products, customer_product_usage, sales_policy_updates
    Rebuild from data.xlsx with:  python scripts/build_seed_db.py

Runtime database (ignored, read-write)  data/runtime.db
    session_memory, sales_interactions, turn_metrics — everything the agent
    writes. Created on first start.

Callers never learn which table lives where: the runtime database is the main
database and the seed is ATTACHed read-only, so unqualified table names resolve
to whichever file holds them and any write to a seed table fails. This module
is the only place that knows the split.

Override either location with the SEED_DB_PATH / RUNTIME_DB_PATH environment
variables (tests point RUNTIME_DB_PATH at a temp file).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths and table ownership
# ---------------------------------------------------------------------------
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_SEED_DB_PATH = _DATA_DIR / "seed.db"
DEFAULT_RUNTIME_DB_PATH = _DATA_DIR / "runtime.db"

SEED_TABLES: tuple[str, ...] = (
    "customers",
    "stripe_products",
    "customer_product_usage",
    "sales_policy_updates",
)
RUNTIME_TABLES: tuple[str, ...] = (
    "session_memory",
    "sales_interactions",
    "turn_metrics",  # DDL lives in app.metrics.init_metrics; ownership is recorded here.
)


def seed_db_path() -> Path:
    """Location of the tracked, read-only seed database (env SEED_DB_PATH overrides)."""
    return Path(os.environ.get("SEED_DB_PATH") or DEFAULT_SEED_DB_PATH)


def runtime_db_path() -> Path:
    """Location of the ignored runtime database (env RUNTIME_DB_PATH overrides)."""
    return Path(os.environ.get("RUNTIME_DB_PATH") or DEFAULT_RUNTIME_DB_PATH)


class SeedDatabaseMissing(RuntimeError):
    """The tracked seed database is not where we expect it."""


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
_connection: sqlite3.Connection | None = None


def get_connection() -> sqlite3.Connection:
    """Return (and cache) the shared connection: runtime as main, seed attached read-only."""
    global _connection
    if _connection is None:
        seed = seed_db_path()
        if not seed.exists():
            raise SeedDatabaseMissing(
                f"seed database not found at {seed}. "
                "Build it with:  python scripts/build_seed_db.py"
            )
        runtime = runtime_db_path()
        runtime.parent.mkdir(parents=True, exist_ok=True)

        # URI filenames so the ATTACH below can ask for mode=ro.
        conn = sqlite3.connect(runtime.resolve().as_uri(), uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("ATTACH DATABASE ? AS seed", (f"{seed.resolve().as_uri()}?mode=ro",))
        _connection = conn
    return _connection


def close_connection() -> None:
    """Close the cached connection so the next call reopens (tests, path changes)."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None


def init_db() -> None:
    """Create runtime tables if they don't exist. Call at app startup."""
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
    # No FK to customers: SQLite cannot reference a table in an attached database.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sales_interactions (
            interaction_id        TEXT PRIMARY KEY,
            customer_id           TEXT NOT NULL,
            sales_rep_id          TEXT,
            interaction_date      TEXT,
            channel               TEXT,
            customer_question     TEXT,
            detected_intent       TEXT,
            mentioned_products    TEXT,
            customer_pain_points  TEXT,
            follow_up_action      TEXT,
            next_step_date        TEXT,
            created_at            TEXT
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
# Customer lookup (seed tables)
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
