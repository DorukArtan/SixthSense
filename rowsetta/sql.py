"""Steps 5-6 - SQL validation and read-only execution.

Owner: TBD

validate(): SQLGlot (dialect="sqlite") parses exactly one statement; only
SELECT or WITH ... SELECT; tables limited to `sales` and `products`; named
parameters in the SQL must match the keys of `params`; then SQLite EXPLAIN
catches unknown columns.

run_query(): opens the snapshot as file:...?mode=ro, sets PRAGMA query_only=ON,
enforces the time limit with a progress handler, fetches max_rows + 1 rows to
detect truncation.

Raise SqlError with kind "syntax" | "column" | "params" (repairable) or
"policy" | "timeout" | "runtime" (not repairable).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from rowsetta.types import QueryResult

ALLOWED_TABLES = frozenset({"sales", "products"})


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def validate(sql: str, params: dict, conn: sqlite3.Connection) -> None:
    """Raise SqlError if the query breaks the policy; return None if it may run."""
    raise NotImplementedError("sql.validate")


def run_query(
    sql: str, params: dict, conn: sqlite3.Connection, *, timeout_s: float, max_rows: int
) -> QueryResult:
    """Execute a validated query under the time limit and row cap."""
    raise NotImplementedError("sql.run_query")
