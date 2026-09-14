"""
The customer list endpoint reads seed data through the shared connection.

This is the one existing caller that queries a seed table directly; it must
keep working unchanged after the seed / runtime split.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app

pytestmark = pytest.mark.unit


def test_customer_list_is_served_from_the_seed_database():
    with TestClient(app) as client:
        response = client.get("/api/customers")
    assert response.status_code == 200
    customers = response.json()
    with sqlite3.connect(database.seed_db_path()) as seed:
        expected = seed.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    assert len(customers) == expected + 1 > 1, "every customer, plus the choice to be a new prospect"
    assert customers[0]["prospect"] is True and customers[0]["customer_id"] is None
    assert {"customer_id", "customer_name", "industry", "annual_payment_volume"} <= set(customers[1])
