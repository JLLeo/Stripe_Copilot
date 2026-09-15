"""
Database access — one connection over two SQLite files.

Seed database   (tracked, read-only)   data/seed.db
    customers, stripe_products, customer_product_usage, sales_policy_updates
    Rebuild from data.xlsx with:  python scripts/build_seed_db.py

Runtime database (ignored, read-write)  data/runtime.db
    sessions, messages, attachments, compactions, handoffs, leads, customer_memory,
    turn_metrics — everything the agent writes.
    Created on first start.

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

from app.paths import DATA_DIR

# ---------------------------------------------------------------------------
# Paths and table ownership
# ---------------------------------------------------------------------------
DEFAULT_SEED_DB_PATH = DATA_DIR / "seed.db"
DEFAULT_RUNTIME_DB_PATH = DATA_DIR / "runtime.db"

SEED_TABLES: tuple[str, ...] = (
    "customers",
    "stripe_products",
    "customer_product_usage",
    "sales_policy_updates",
)
RUNTIME_TABLES: tuple[str, ...] = (
    "sessions",
    "messages",
    "handoffs",
    "leads",
    "customer_memory",
    "attachments",
    "compactions",
    "turn_metrics",  # DDL lives in app.metrics.init_metrics; ownership is recorded here.
)

# The Customer Profile as the agent may see it: column -> label. Shared by the
# customer block and the get_my_profile tool so the two never drift apart.
CUSTOMER_PROFILE_FIELDS: dict[str, str] = {
    "company_stage": "Company stage",
    "industry": "Industry",
    "business_model": "Business model",
    "use_case": "Use case",
    "country": "Country",
    "annual_payment_volume": "Annual payment volume (USD)",
    "monthly_transactions": "Monthly transactions",
    "average_order_value": "Average order value (USD)",
    "primary_pain_point": "Primary pain point",
    "fraud_risk_level": "Fraud risk level",
    "integration_maturity": "Integration maturity",
}


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
    # No FK to customers: SQLite cannot reference a table in an attached database.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id      TEXT PRIMARY KEY,
            customer_id     TEXT,
            customer_block  TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            ended_at        TEXT,
            last_prompt_tokens INTEGER NOT NULL DEFAULT 0
        )
    """)
    _add_missing_columns(conn, "sessions", {"ended_at": "TEXT", "last_prompt_tokens": "INTEGER NOT NULL DEFAULT 0"})
    # Working memory: one row per message, only ever inserted; content is never rewritten.
    # `cleared_at` is the one column that changes: a spent tool result rendered as a stub (ADR 0006).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id         TEXT NOT NULL REFERENCES sessions(session_id),
            role               TEXT NOT NULL,
            content            TEXT,
            reasoning_content  TEXT,
            tool_calls_json    TEXT,
            tool_call_id       TEXT,
            name               TEXT,
            created_at         TEXT NOT NULL,
            cleared_at         TEXT
        )
    """)
    _add_missing_columns(conn, "messages", {"cleared_at": "TEXT"})
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id)")
    # An Attachment is a long customer message kept out of working memory and read in pieces.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attachments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL REFERENCES sessions(session_id),
            turn_id     TEXT NOT NULL,
            content     TEXT NOT NULL,
            chars       INTEGER NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)
    # A Compaction replaces every message up to `through_message_id` with one rolling summary.
    # Rows stay where they are; rendering starts after the latest compaction.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS compactions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id            TEXT NOT NULL REFERENCES sessions(session_id),
            through_message_id    INTEGER NOT NULL,
            summary               TEXT NOT NULL,   -- the rendered summary message, preface included
            skills_json           TEXT NOT NULL,   -- skills loaded so far, carried from one summary to the next
            model                 TEXT NOT NULL,
            prompt_tokens_before  INTEGER NOT NULL,
            created_at            TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_compactions_session ON compactions(session_id, id)")
    # A Handoff row is created when the model proposes one and resolved when the customer answers.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS handoffs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    TEXT NOT NULL REFERENCES sessions(session_id),
            customer_id   TEXT,
            tool_call_id  TEXT NOT NULL,
            team          TEXT NOT NULL,
            reason        TEXT NOT NULL,
            evidence      TEXT NOT NULL,
            status        TEXT NOT NULL,  -- pending | confirmed | declined
            created_at    TEXT NOT NULL,
            resolved_at   TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_handoffs_session ON handoffs(session_id, status)")
    # A Lead is what the agent learned about a Prospect: one row per session, refined as they talk.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id                         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id                 TEXT NOT NULL UNIQUE REFERENCES sessions(session_id),
            company                    TEXT,
            business_model             TEXT,
            annual_volume_usd          INTEGER,
            timeline                   TEXT,
            needs                      TEXT,
            qualification_notes        TEXT,
            recommended_products_json  TEXT,
            created_at                 TEXT NOT NULL,
            updated_at                 TEXT NOT NULL
        )
    """)
    # Customer Memory: durable facts that outlive a session. A fact is never edited in
    # place — a correction writes a new row and marks the old one superseded.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS customer_memory (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id    TEXT NOT NULL,
            kind           TEXT NOT NULL,   -- need | objection | preference | commitment | stage
            fact           TEXT NOT NULL,
            source_turn    TEXT NOT NULL,   -- the turn (or SessionEnd pass) that wrote it
            source         TEXT NOT NULL,   -- remember | reflection
            confidence     REAL NOT NULL,
            status         TEXT NOT NULL,   -- active | superseded | retracted
            superseded_by  INTEGER,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_customer ON customer_memory(customer_id, status)")
    conn.commit()


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Runtime databases from earlier versions gain new columns in place."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, declaration in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


# ---------------------------------------------------------------------------
# Sessions and working memory
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_session(session_id: str) -> dict[str, Any] | None:
    """Session binding and its SessionStart customer block, or None if unseen."""
    row = get_connection().execute(
        "SELECT session_id, customer_id, customer_block, created_at, ended_at, last_prompt_tokens "
        "FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return dict(row) if row else None


def set_last_prompt_tokens(session_id: str, prompt_tokens: int) -> None:
    """What the provider reported for the latest request — the number context relief reads (ADR 0006)."""
    conn = get_connection()
    conn.execute("UPDATE sessions SET last_prompt_tokens = ? WHERE session_id = ?", (int(prompt_tokens), session_id))
    conn.commit()


def end_session(session_id: str) -> bool:
    """Mark the session ended. False if it already was — the customer can end a conversation once."""
    conn = get_connection()
    cur = conn.execute("UPDATE sessions SET ended_at = ? WHERE session_id = ? AND ended_at IS NULL", (_now(), session_id))
    conn.commit()
    return cur.rowcount == 1


def create_session(session_id: str, customer_id: str | None, customer_block: str) -> dict[str, Any]:
    """Bind a new session to a customer (or none, for a prospect) and freeze its customer block."""
    conn = get_connection()
    conn.execute(
        # OR IGNORE: two first turns racing on a new session both land on the same row.
        "INSERT OR IGNORE INTO sessions (session_id, customer_id, customer_block, created_at) VALUES (?, ?, ?, ?)",
        (session_id, customer_id or None, customer_block, _now()),
    )
    conn.commit()
    return load_session(session_id)  # type: ignore[return-value]


CLEARED_STUB = "[cleared: earlier {name} result ({chars:,} characters); call the tool again if you need it]"


def load_message_rows(session_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The latest compaction (or None) and the rows after it, each as {id, role, tool, chars, message}.

    `message` is the wire shape the model sees: a cleared tool result is rendered as a
    one-line stub, the row's content untouched. `tool` names the tool a tool row answers.
    """
    compaction = latest_compaction(session_id)
    after = compaction["through_message_id"] if compaction else 0
    rows = get_connection().execute(
        """
        SELECT id, role, content, reasoning_content, tool_calls_json, tool_call_id, name, cleared_at
        FROM messages WHERE session_id = ? AND id > ? ORDER BY id
        """,
        (session_id, after),
    ).fetchall()
    names: dict[str, str] = {}  # tool call id -> tool name, from the assistant row that made the call
    out: list[dict[str, Any]] = []
    for r in rows:
        msg: dict[str, Any] = {"role": r["role"], "content": r["content"]}
        if r["reasoning_content"] is not None:
            msg["reasoning_content"] = r["reasoning_content"]
        if r["tool_calls_json"]:
            msg["tool_calls"] = json.loads(r["tool_calls_json"])
            for call in msg["tool_calls"]:
                names[call["id"]] = call["function"]["name"]
        if r["tool_call_id"]:
            msg["tool_call_id"] = r["tool_call_id"]
        if r["name"]:
            msg["name"] = r["name"]
        tool = names.get(r["tool_call_id"]) if r["role"] == "tool" else None
        original = len(r["content"] or "")
        if r["cleared_at"]:
            msg["content"] = CLEARED_STUB.format(name=tool or "tool", chars=original)
        out.append({
            "id": r["id"], "role": r["role"], "tool": tool, "cleared": bool(r["cleared_at"]), "message": msg,
            "chars": len(msg["content"] or ""),  # as rendered — what sizing sees
            "original_chars": original,
        })
    return compaction, out


def load_messages(session_id: str) -> list[dict[str, Any]]:
    """Working memory in wire shape, oldest first: the latest summary (if any), then every message after it."""
    compaction, rows = load_message_rows(session_id)
    messages = [r["message"] for r in rows]
    if compaction:
        messages.insert(0, {"role": "user", "content": compaction["summary"]})
    return messages


def clear_tool_results(session_id: str, *, min_chars: int, exempt: tuple[str, ...]) -> list[dict[str, Any]]:
    """Render spent tool results as stubs: every uncleared tool row after the latest compaction, over `min_chars`,
    from a tool not in `exempt`. Returns what was cleared ({id, tool, chars}). Content is kept."""
    _, rows = load_message_rows(session_id)
    victims = [r for r in rows if r["role"] == "tool" and not r["cleared"] and r["original_chars"] > min_chars and r["tool"] not in exempt]
    if victims:
        conn = get_connection()
        now = _now()
        conn.executemany("UPDATE messages SET cleared_at = ? WHERE id = ?", [(now, r["id"]) for r in victims])
        conn.commit()
    return [{"id": r["id"], "tool": r["tool"], "chars": r["original_chars"]} for r in victims]


def latest_compaction(session_id: str) -> dict[str, Any] | None:
    row = get_connection().execute(
        "SELECT * FROM compactions WHERE session_id = ? ORDER BY id DESC LIMIT 1", (session_id,)
    ).fetchone()
    if row is None:
        return None
    compaction = dict(row)
    compaction["skills"] = json.loads(compaction.pop("skills_json") or "[]")
    return compaction


def record_compaction(
    session_id: str, *, through_message_id: int, summary: str, skills: list[str], model: str, prompt_tokens_before: int
) -> dict[str, Any]:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO compactions (session_id, through_message_id, summary, skills_json, model, prompt_tokens_before, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, through_message_id, summary, json.dumps(skills), model, prompt_tokens_before, _now()),
    )
    conn.commit()
    return latest_compaction(session_id)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
def create_attachment(session_id: str, turn_id: str, content: str) -> dict[str, Any]:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO attachments (session_id, turn_id, content, chars, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, turn_id, content, len(content), _now()),
    )
    conn.commit()
    return {"id": int(cur.lastrowid), "session_id": session_id, "chars": len(content)}


def list_attachments(session_id: str) -> list[dict[str, Any]]:
    """The session's attachments without their content — what a summary can point the model back to."""
    rows = get_connection().execute(
        "SELECT id, chars FROM attachments WHERE session_id = ? ORDER BY id", (session_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_attachment(attachment_id: int, session_id: str) -> dict[str, Any] | None:
    """An attachment of this session, or None — another session's attachments cannot be named."""
    row = get_connection().execute(
        "SELECT * FROM attachments WHERE id = ? AND session_id = ?", (attachment_id, session_id)
    ).fetchone()
    return dict(row) if row else None


def append_messages(session_id: str, messages: list[dict[str, Any]]) -> None:
    """Append wire-shaped messages to a session. Never updates or deletes."""
    conn = get_connection()
    now = _now()
    conn.executemany(
        """
        INSERT INTO messages
            (session_id, role, content, reasoning_content, tool_calls_json, tool_call_id, name, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                session_id,
                m["role"],
                m.get("content"),
                m.get("reasoning_content"),
                json.dumps(m["tool_calls"], ensure_ascii=False) if m.get("tool_calls") else None,
                m.get("tool_call_id"),
                m.get("name"),
                now,
            )
            for m in messages
        ],
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Handoffs
# ---------------------------------------------------------------------------
HANDOFF_PENDING = "pending"  # proposed; the customer has not answered
HANDOFF_CONFIRMED = "confirmed"  # the customer said yes; a team takes over
HANDOFF_DECLINED = "declined"  # the customer said no, or moved on; nobody is contacted
HANDOFF_ABANDONED = "abandoned"  # proposed, but the turn never reached the customer (disconnect); nobody is contacted


def create_pending_handoff(
    *, session_id: str, customer_id: str | None, tool_call_id: str, team: str, reason: str, evidence: str
) -> int:
    conn = get_connection()
    cur = conn.execute(
        """
        INSERT INTO handoffs (session_id, customer_id, tool_call_id, team, reason, evidence, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, customer_id, tool_call_id, team, reason, evidence, HANDOFF_PENDING, _now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def pending_handoff(session_id: str) -> dict[str, Any] | None:
    row = get_connection().execute(
        "SELECT * FROM handoffs WHERE session_id = ? AND status = ? ORDER BY id DESC LIMIT 1",
        (session_id, HANDOFF_PENDING),
    ).fetchone()
    return dict(row) if row else None


def resolve_handoff(handoff_id: int, status: str) -> bool:
    """Move a pending handoff to `status`. False if it was no longer pending — someone else resolved it first."""
    conn = get_connection()
    cur = conn.execute(
        "UPDATE handoffs SET status = ?, resolved_at = ? WHERE id = ? AND status = ?",
        (status, _now(), handoff_id, HANDOFF_PENDING),
    )
    conn.commit()
    return cur.rowcount == 1


def count_handoffs(since: str, status: str = HANDOFF_CONFIRMED) -> int:
    return get_connection().execute(
        "SELECT COUNT(*) FROM handoffs WHERE status = ? AND resolved_at >= ?", (status, since)
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------
LEAD_FIELDS = ("company", "business_model", "annual_volume_usd", "timeline", "needs", "qualification_notes")


def upsert_lead(session_id: str, fields: dict[str, Any], recommended_products: list[str] | None) -> dict[str, Any]:
    """Write the session's Lead, keeping every earlier fact the new call does not restate."""
    conn = get_connection()
    now = _now()
    values = {k: fields.get(k) for k in LEAD_FIELDS}
    products = json.dumps(recommended_products) if recommended_products is not None else None
    conn.execute(
        """
        INSERT INTO leads (session_id, company, business_model, annual_volume_usd, timeline, needs,
                           qualification_notes, recommended_products_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            company                   = COALESCE(excluded.company, leads.company),
            business_model            = COALESCE(excluded.business_model, leads.business_model),
            annual_volume_usd         = COALESCE(excluded.annual_volume_usd, leads.annual_volume_usd),
            timeline                  = COALESCE(excluded.timeline, leads.timeline),
            needs                     = COALESCE(excluded.needs, leads.needs),
            qualification_notes       = COALESCE(excluded.qualification_notes, leads.qualification_notes),
            recommended_products_json = COALESCE(excluded.recommended_products_json, leads.recommended_products_json),
            updated_at                = excluded.updated_at
        """,
        (session_id, *(values[k] for k in LEAD_FIELDS), products, now, now),
    )
    conn.commit()
    return get_lead(session_id)  # type: ignore[return-value]


def _lead_row(row: sqlite3.Row) -> dict[str, Any]:
    lead = dict(row)
    lead["recommended_products"] = json.loads(lead.pop("recommended_products_json") or "[]")
    return lead


def get_lead(session_id: str) -> dict[str, Any] | None:
    row = get_connection().execute("SELECT * FROM leads WHERE session_id = ?", (session_id,)).fetchone()
    return _lead_row(row) if row else None


def list_leads(limit: int = 50) -> list[dict[str, Any]]:
    """Most recently updated first — the queue for whoever follows up."""
    rows = get_connection().execute("SELECT * FROM leads ORDER BY updated_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
    return [_lead_row(r) for r in rows]


def count_leads(since: str) -> int:
    return get_connection().execute("SELECT COUNT(*) FROM leads WHERE created_at >= ?", (since,)).fetchone()[0]


def annual_payment_volume(session_id: str, customer_id: str | None) -> int:
    """What is known of the customer's yearly volume: the profile for a customer, the Lead for a prospect; 0 if nothing."""
    if customer_id:
        return int((get_customer(customer_id) or {}).get("annual_payment_volume") or 0)
    return int((get_lead(session_id) or {}).get("annual_volume_usd") or 0)


# ---------------------------------------------------------------------------
# Customer Memory
# ---------------------------------------------------------------------------
MEMORY_KINDS = ("need", "objection", "preference", "commitment", "stage")
MEMORY_ACTIVE = "active"
MEMORY_SUPERSEDED = "superseded"  # a later fact replaced it
MEMORY_RETRACTED = "retracted"  # the customer said it was wrong or no longer true


def add_memory(customer_id: str, *, kind: str, fact: str, source_turn: str, source: str, confidence: float) -> dict[str, Any]:
    conn = get_connection()
    now = _now()
    cur = conn.execute(
        """
        INSERT INTO customer_memory (customer_id, kind, fact, source_turn, source, confidence, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (customer_id, kind, fact, source_turn, source, confidence, MEMORY_ACTIVE, now, now),
    )
    conn.commit()
    return get_memory(int(cur.lastrowid))  # type: ignore[return-value]


def get_memory(memory_id: int) -> dict[str, Any] | None:
    row = get_connection().execute("SELECT * FROM customer_memory WHERE id = ?", (memory_id,)).fetchone()
    return dict(row) if row else None


def active_memories(customer_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """The facts currently believed about a customer, most recently updated first."""
    sql = "SELECT * FROM customer_memory WHERE customer_id = ? AND status = ? ORDER BY updated_at DESC, id DESC"
    params: tuple[Any, ...] = (customer_id, MEMORY_ACTIVE)
    if limit is not None:
        sql += " LIMIT ?"
        params += (limit,)
    return [dict(r) for r in get_connection().execute(sql, params).fetchall()]


def session_memories(session_id: str, customer_id: str) -> list[dict[str, Any]]:
    """The customer's active facts that were recorded during this session (by a turn or its SessionEnd pass)."""
    rows = get_connection().execute(
        """
        SELECT * FROM customer_memory
        WHERE customer_id = ? AND status = ?
          AND source_turn IN (SELECT turn_id FROM turn_metrics WHERE session_id = ?)
        ORDER BY id
        """,
        (customer_id, MEMORY_ACTIVE, session_id),
    ).fetchall()
    return [dict(r) for r in rows]


def _settle_memory(memory_id: int, customer_id: str, status: str, superseded_by: int | None) -> bool:
    """Move an active fact to `status`. False if it is not this customer's or no longer active."""
    conn = get_connection()
    cur = conn.execute(
        "UPDATE customer_memory SET status = ?, superseded_by = ?, updated_at = ? "
        "WHERE id = ? AND customer_id = ? AND status = ?",
        (status, superseded_by, _now(), memory_id, customer_id, MEMORY_ACTIVE),
    )
    conn.commit()
    return cur.rowcount == 1


def supersede_memory(memory_id: int, customer_id: str, *, by: int) -> bool:
    return _settle_memory(memory_id, customer_id, MEMORY_SUPERSEDED, by)


def retract_memory(memory_id: int, customer_id: str) -> bool:
    return _settle_memory(memory_id, customer_id, MEMORY_RETRACTED, None)


def dangling_tool_call_ids(working_memory: list[dict[str, Any]]) -> list[str]:
    """Tool calls in the last assistant message that have no tool result after it — working memory the model cannot be sent."""
    for i in range(len(working_memory) - 1, -1, -1):
        msg = working_memory[i]
        if msg["role"] == "assistant":
            wanted = [c["id"] for c in msg.get("tool_calls") or []]
            answered = {m.get("tool_call_id") for m in working_memory[i + 1:] if m["role"] == "tool"}
            return [c for c in wanted if c not in answered]
        if msg["role"] == "user":
            return []
    return []


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


def list_products(group: str | None = None) -> list[dict[str, Any]]:
    """The product catalogue, optionally one product group (case-insensitive), sorted by group then name."""
    conn = get_connection()
    if group:
        rows = conn.execute(
            "SELECT * FROM stripe_products WHERE LOWER(product_group) = LOWER(?) ORDER BY product_name",
            (group,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM stripe_products ORDER BY product_group, product_name").fetchall()
    return [dict(r) for r in rows]


def list_product_groups() -> list[str]:
    rows = get_connection().execute(
        "SELECT DISTINCT product_group FROM stripe_products ORDER BY product_group"
    ).fetchall()
    return [r[0] for r in rows]


def get_active_policies() -> list[dict[str, Any]]:
    """Return the active rows of the policy register."""
    rows = get_connection().execute(
        """
        SELECT * FROM sales_policy_updates
        WHERE is_active = 1
        ORDER BY policy_area, effective_start_date DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]
