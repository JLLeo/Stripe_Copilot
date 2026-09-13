"""
Tests for the seed / runtime database split.

Domain seed data (customers, products, usage, policies) lives in a tracked,
read-only seed database. Everything the agent writes lives in an ignored
runtime database. Callers see one connection and never learn which is which.
"""

import hashlib
import sqlite3

import pytest

from app import database
from app.metrics import TurnRecord, init_metrics, record_turn

pytestmark = pytest.mark.unit


def _tables(path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def runtime_db(tmp_path, monkeypatch):
    """Point the runtime database at a fresh temp file for this test."""
    path = tmp_path / "runtime.db"
    monkeypatch.setenv("RUNTIME_DB_PATH", str(path))
    database.close_connection()
    yield path
    database.close_connection()


# =========================================================================
# Seed database: tracked, domain data only
# =========================================================================
def test_seed_database_holds_exactly_the_domain_tables():
    assert database.seed_db_path().exists(), "seed database must be checked in"
    assert _tables(database.seed_db_path()) == {
        "customers", "stripe_products", "customer_product_usage", "sales_policy_updates",
    }
    assert set(database.SEED_TABLES) == _tables(database.seed_db_path())


def test_seed_database_uses_a_rollback_journal():
    # WAL mode would create -wal/-shm sidecar files next to a tracked file.
    conn = sqlite3.connect(database.seed_db_path())
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal"
    finally:
        conn.close()


# =========================================================================
# Runtime database: created on first start, holds what the agent writes
# =========================================================================
def test_runtime_database_is_created_on_init(runtime_db):
    assert not runtime_db.exists()
    database.init_db()
    init_metrics()
    assert runtime_db.exists()
    assert _tables(runtime_db) == set(database.RUNTIME_TABLES)
    assert _tables(runtime_db).isdisjoint(database.SEED_TABLES)


# =========================================================================
# One connection, both databases
# =========================================================================
def test_seed_tables_are_readable_through_the_shared_connection(runtime_db):
    database.init_db()
    conn = database.get_connection()
    customer_id = conn.execute("SELECT customer_id FROM customers LIMIT 1").fetchone()[0]

    assert database.get_customer(customer_id)["customer_id"] == customer_id
    assert database.get_active_policies()
    assert conn.execute("SELECT COUNT(*) FROM stripe_products").fetchone()[0] > 0


def test_runtime_writes_leave_the_seed_file_untouched(runtime_db):
    before = _sha256(database.seed_db_path())
    database.init_db()
    init_metrics()
    conn = database.get_connection()
    customer_id = conn.execute("SELECT customer_id FROM customers LIMIT 1").fetchone()[0]

    database.create_session("s1", customer_id, "Customer: test")
    database.append_messages("s1", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}])
    record_turn(TurnRecord(turn_id="t1", session_id="s1", customer_id=customer_id, model="m"))

    assert _sha256(database.seed_db_path()) == before
    assert database.load_session("s1")["customer_id"] == customer_id
    assert [m["content"] for m in database.load_messages("s1")] == ["hi", "hello"]


def test_seed_tables_cannot_be_written(runtime_db):
    database.init_db()
    conn = database.get_connection()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO customers (customer_id, customer_name) VALUES ('x', 'x')")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM sales_policy_updates")


def test_missing_seed_database_gives_an_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SEED_DB_PATH", str(tmp_path / "nope.db"))
    monkeypatch.setenv("RUNTIME_DB_PATH", str(tmp_path / "runtime.db"))
    database.close_connection()
    try:
        with pytest.raises(database.SeedDatabaseMissing, match="build_seed_db"):
            database.get_connection()
    finally:
        database.close_connection()


def test_messages_round_trip_every_wire_field(runtime_db):
    database.init_db()
    database.create_session("s1", None, "Customer: unknown")
    database.append_messages("s1", [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "reasoning_content": "hmm",
         "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "content": "{}", "tool_call_id": "c1", "name": "f"},
    ])
    assert database.load_messages("s1") == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "reasoning_content": "hmm",
         "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "content": "{}", "tool_call_id": "c1", "name": "f"},
    ]
