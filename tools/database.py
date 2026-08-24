import re
import sqlite3

from config import DB_PATH
from .registry import tool

MAX_ROWS = 100

# Tables the agent is allowed to change. Reading is allowed everywhere.
WRITABLE_TABLES = {"customers", "orders"}

BAD_WORDS = re.compile(
    r"\b(drop|delete|truncate|alter|attach|detach|pragma|create|replace|vacuum)\b",
    re.IGNORECASE,
)


class DBError(Exception):
    pass


def _connect(read_only: bool):
    if not DB_PATH.exists():
        raise DBError(f"database file not found at {DB_PATH}")
    if read_only:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _check_table(table: str):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise DBError(f"'{table}' is not a valid table name.")
    if table not in WRITABLE_TABLES:
        raise DBError(
            f"table '{table}' cannot be changed. "
            f"Writable tables: {', '.join(sorted(WRITABLE_TABLES))}"
        )


def _check_column(col: str):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", col):
        raise DBError(f"'{col}' is not a valid column name.")


def _rows_to_text(rows) -> str:
    if not rows:
        return "(no rows)"
    header = " | ".join(rows[0].keys())
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(" | ".join("" if v is None else str(v) for v in r))
    return "\n".join(lines)


@tool
def db_schema() -> str:
    """Show every table in the database and its columns. Call this FIRST before
    writing any query, so you use real table and column names.
    """
    conn = _connect(read_only=True)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()

        out = []
        for t in tables:
            name = t["name"]
            cols = conn.execute(f"PRAGMA table_info({name})").fetchall()
            col_text = ", ".join(f"{c['name']} {c['type']}" for c in cols)
            mark = "" if name in WRITABLE_TABLES else "   (read-only)"
            out.append(f"{name}({col_text}){mark}")
        return "\n".join(out) if out else "(database has no tables)"
    finally:
        conn.close()


@tool
def db_query(sql: str) -> str:
    """Run a read-only SQL query and get the rows back. Only SELECT is allowed.
    Use db_schema first so your column names are correct.

    Args:
        sql: A single SELECT statement, for example
             "SELECT name, city FROM customers WHERE plan = 'pro'".
    """
    clean = sql.strip().rstrip(";").strip()

    if ";" in clean:
        raise DBError("only one statement is allowed. Remove the extra ';'.")
    if not re.match(r"^(select|with)\b", clean, re.IGNORECASE):
        raise DBError("only SELECT queries are allowed here. Use db_insert or db_update to change data.")
    if BAD_WORDS.search(clean):
        raise DBError("that query contains a command that is not allowed.")
    if not re.search(r"\blimit\b", clean, re.IGNORECASE):
        clean += f" LIMIT {MAX_ROWS}"

    conn = _connect(read_only=True)
    try:
        rows = conn.execute(clean).fetchall()
    except sqlite3.Error as e:
        raise DBError(f"SQL error: {e}. Check db_schema for the correct names.")
    finally:
        conn.close()

    return f"{len(rows)} row(s)\n{_rows_to_text(rows)}"


@tool
def db_insert(table: str, values: dict) -> str:
    """Add one new row to a table. Give the column names and their values.
    Do not write SQL here.

    Args:
        table: The table to add the row to, for example "customers".
        values: Column name to value, for example {"name": "Sam", "city": "Delhi"}.
    """
    _check_table(table)
    if not values:
        raise DBError("values cannot be empty.")
    for col in values:
        _check_column(col)

    cols = list(values.keys())
    placeholders = ", ".join("?" for _ in cols)
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"

    conn = _connect(read_only=False)
    try:
        cur = conn.execute(sql, list(values.values()))
        conn.commit()
        return f"Added row {cur.lastrowid} to '{table}'."
    except sqlite3.Error as e:
        raise DBError(f"insert failed: {e}")
    finally:
        conn.close()


@tool
def db_update(table: str, values: dict, where_column: str, where_value: str) -> str:
    """Change existing rows in a table. A filter is required, so you can never
    change every row by accident. Run db_query first to see which rows match.

    Args:
        table: The table to change, for example "customers".
        values: Columns to set, for example {"plan": "pro"}.
        where_column: The column to filter on, for example "id".
        where_value: The value that column must equal, for example "3".
    """
    _check_table(table)
    if not values:
        raise DBError("values cannot be empty.")
    for col in values:
        _check_column(col)
    _check_column(where_column)

    sets = ", ".join(f"{c} = ?" for c in values)
    sql = f"UPDATE {table} SET {sets} WHERE {where_column} = ?"

    conn = _connect(read_only=False)
    try:
        cur = conn.execute(sql, list(values.values()) + [where_value])
        conn.commit()
        if cur.rowcount == 0:
            return f"No rows matched {where_column} = {where_value}. Nothing changed."
        return f"Changed {cur.rowcount} row(s) in '{table}'."
    except sqlite3.Error as e:
        raise DBError(f"update failed: {e}")
    finally:
        conn.close()
@tool
def db_delete(table: str, where_column: str, where_value: str) -> str:
    """Delete rows from a table. A filter is required. Run db_query first to
    see exactly which rows will go.

    Args:
        table: The table to delete from.
        where_column: The column to filter on, for example "id".
        where_value: The value that column must equal.
    """
    _check_table(table)
    _check_column(where_column)

    conn = _connect(read_only=False)
    try:
        cur = conn.execute(f"DELETE FROM {table} WHERE {where_column} = ?", (where_value,))
        conn.commit()
        return f"Deleted {cur.rowcount} row(s) from '{table}'."
    except sqlite3.Error as e:
        raise DBError(f"delete failed: {e}")
    finally:
        conn.close()