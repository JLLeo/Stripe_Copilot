import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "stripe_sales_copilot.db"


def execute_query(query: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(query)
        if query.strip().lower().startswith("select") or query.strip().lower().startswith("pragma"):
            rows = cursor.fetchall()
            if not rows:
                print("No rows returned.")
                return
            columns = list(rows[0].keys())
            print(" | ".join(columns))
            print("-" * 80)
            for row in rows:
                print(" | ".join(str(row[col]) for col in columns))
        else:
            conn.commit()
            print("Query executed successfully.")
    except sqlite3.Error as exc:
        print(f"SQL error: {exc}")
    finally:
        conn.close()


def main():
    print(f"SQLite DB: {DB_PATH}")
    print("Type your SQL query below. Type 'exit' to quit.")

    while True:
        try:
            query = input("SQL> ").strip()
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break

        if not query:
            continue
        if query.lower() in {"exit", "quit"}:
            print("Goodbye!")
            break

        execute_query(query)


if __name__ == "__main__":
    main()
