"""Create the demo SQL database the agent queries.

Run once from the project root:   python scripts/setup_db.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DB_PATH   # noqa: E402

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.executescript("""
CREATE TABLE IF NOT EXISTS customers (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL,
    email   TEXT,
    city    TEXT,
    plan    TEXT DEFAULT 'free'
);

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    product     TEXT NOT NULL,
    amount      REAL NOT NULL,
    order_date  TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);
""")

c.executemany(
    "INSERT INTO customers (name, email, city, plan) VALUES (?, ?, ?, ?)",
    [
        ("Anita Rao",    "anita@example.com",  "Hyderabad", "pro"),
        ("Ben Carter",   "ben@example.com",    "Austin",    "free"),
        ("Chen Wei",     "chen@example.com",   "Singapore", "pro"),
        ("Diana Lopez",  "diana@example.com",  "Madrid",    "enterprise"),
    ],
)

c.executemany(
    "INSERT INTO orders (customer_id, product, amount, order_date) VALUES (?, ?, ?, ?)",
    [
        (1, "Laptop stand", 45.00,  "2026-07-02"),
        (1, "Keyboard",     120.50, "2026-07-18"),
        (2, "Mouse",        25.00,  "2026-08-01"),
        (3, "Monitor",      310.00, "2026-08-05"),
        (3, "Cable pack",   18.75,  "2026-08-06"),
        (4, "Desk",         540.00, "2026-08-11"),
    ],
)

conn.commit()
conn.close()
print(f"created {DB_PATH}")