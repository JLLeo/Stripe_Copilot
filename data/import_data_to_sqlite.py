from pathlib import Path
import sqlite3
from typing import Iterable

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data.xlsx"
DB_PATH = ROOT / "data" / "stripe_sales_copilot.db"

CREATE_TABLES = {
    "customers": """
        CREATE TABLE customers (
            customer_id TEXT PRIMARY KEY,
            customer_name TEXT NOT NULL,
            company_stage TEXT,
            industry TEXT,
            use_case TEXT,
            business_model TEXT,
            country TEXT,
            annual_payment_volume INTEGER,
            monthly_transactions INTEGER,
            average_order_value REAL,
            primary_pain_point TEXT,
            fraud_risk_level TEXT,
            integration_maturity TEXT,
            created_at TEXT
        )
    """,
    "stripe_products": """
        CREATE TABLE stripe_products (
            product_id TEXT PRIMARY KEY,
            product_name TEXT NOT NULL,
            product_group TEXT,
            product_category TEXT,
            short_description TEXT,
            primary_use_case TEXT,
            target_customer_type TEXT,
            complexity_level TEXT,
            requires_sales_assist BOOLEAN,
            requires_compliance_review BOOLEAN
        )
    """,
    "customer_product_usage": """
        CREATE TABLE customer_product_usage (
            usage_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            usage_status TEXT,
            start_date TEXT,
            monthly_volume INTEGER,
            monthly_revenue REAL,
            adoption_level TEXT,
            notes TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
            FOREIGN KEY (product_id) REFERENCES stripe_products(product_id)
        )
    """,
    "sales_policy_updates": """
        CREATE TABLE sales_policy_updates (
            policy_id TEXT PRIMARY KEY,
            product_id TEXT,
            policy_area TEXT NOT NULL,
            policy_title TEXT,
            policy_summary TEXT,
            escalation_team TEXT,
            effective_start_date TEXT,
            effective_end_date TEXT,
            is_active BOOLEAN,
            FOREIGN KEY (product_id) REFERENCES stripe_products(product_id)
        )
    """,
    "sales_interactions": """
        CREATE TABLE sales_interactions (
            interaction_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            sales_rep_id TEXT,
            interaction_date TEXT,
            channel TEXT,
            customer_question TEXT,
            detected_intent TEXT,
            mentioned_products TEXT,
            customer_pain_points TEXT,
            follow_up_action TEXT,
            next_step_date TEXT,
            created_at TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
        )
    """,
}

SHEET_CONFIG = {
    "customers": {
        "table": "customers",
        "columns": [
            "customer_id",
            "customer_name",
            "company_stage",
            "industry",
            "use_case",
            "business_model",
            "country",
            "annual_payment_volume",
            "monthly_transactions",
            "average_order_value",
            "primary_pain_point",
            "fraud_risk_level",
            "integration_maturity",
            "created_at",
        ],
    },
    "stripe_products": {
        "table": "stripe_products",
        "columns": [
            "product_id",
            "product_name",
            "product_group",
            "product_category",
            "short_description",
            "primary_use_case",
            "target_customer_type",
            "complexity_level",
            "requires_sales_assist",
            "requires_compliance_review",
        ],
    },
    "customer_product_usage": {
        "table": "customer_product_usage",
        "columns": [
            "usage_id",
            "customer_id",
            "product_id",
            "usage_status",
            "start_date",
            "monthly_volume",
            "monthly_revenue",
            "adoption_level",
            "notes",
        ],
    },
    "sales_policy_updates": {
        "table": "sales_policy_updates",
        "columns": [
            "policy_id",
            "product_id",
            "policy_area",
            "policy_title",
            "policy_summary",
            "escalation_team",
            "effective_start_date",
            "effective_end_date",
            "is_active",
        ],
    },
    "sales_interactions": {
        "table": "sales_interactions",
        "columns": [
            "interaction_id",
            "customer_id",
            "sales_rep_id",
            "interaction_date",
            "channel",
            "customer_question",
            "detected_intent",
            "mentioned_products",
            "customer_pain_points",
            "follow_up_action",
            "next_step_date",
            "created_at",
        ],
    },
}


def normalize_value(value):
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.to_pydatetime().isoformat()
    if isinstance(value, (np.datetime64,)):
        return pd.Timestamp(value).to_pydatetime().isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is pd.NA:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if pd.isna(value):
        return None
    return value


def clean_dataframe(df: pd.DataFrame, columns: Iterable[str]) -> list[tuple]:
    available = [col for col in columns if col in df.columns]
    rows = []
    for record in df[available].to_dict(orient="records"):
        row = []
        for col in available:
            val = normalize_value(record.get(col))
            if col in {"requires_sales_assist", "requires_compliance_review", "is_active"} and isinstance(val, bool):
                val = int(val)
            row.append(val)
        rows.append(tuple(row))
    return rows


def create_database():
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    for table_name, ddl in CREATE_TABLES.items():
        conn.execute(ddl)

    for sheet_name, cfg in SHEET_CONFIG.items():
        df = pd.read_excel(DATA_FILE, sheet_name=sheet_name)
        rows = clean_dataframe(df, cfg["columns"])
        if not rows:
            continue
        columns = [col for col in cfg["columns"] if col in df.columns]
        placeholders = ", ".join("?" for _ in columns)
        insert_sql = f"INSERT INTO {cfg['table']} ({', '.join(columns)}) VALUES ({placeholders})"
        conn.executemany(insert_sql, rows)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_database()
    print(f"Imported Excel data into {DB_PATH}")
