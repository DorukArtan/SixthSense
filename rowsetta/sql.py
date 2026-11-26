"""Steps 5-6 - SQL validation and read-only execution.

Owner: Mehmet Doruk Artan

validate(): SQLGlot (dialect="sqlite") parses exactly one statement; only
SELECT or WITH ... SELECT; tables limited to `sales` and `products`; named
parameters in the SQL must match the keys of `params`; then SQLite EXPLAIN
catches unknown columns.

connect_readonly(): opens the snapshot with mode=ro and PRAGMA query_only=ON,
and enforces the same table allowlist on SQLite reads.
run_query(): validates and executes a query under a deadline, fetching one
extra row to detect truncation.

Raise SqlError with kind "syntax" | "column" | "params" (repairable) or
"policy" | "timeout" | "runtime" (not repairable).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from math import isfinite
from pathlib import Path
from time import perf_counter

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

from rowsetta.types import QueryResult, SqlError

ALLOWED_TABLES = frozenset({"sales", "products"})
SELECT_STATEMENTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)
PROGRESS_INTERVAL = 1_000
TIMEOUT_MESSAGE = "SQL query exceeded its time limit."


class _ParameterBindings(dict):
    """Record SQLite's binding names and supply NULL for missing values during EXPLAIN."""

    def __init__(self, params: dict):
        super().__init__(params)
        self.names: set[str] = set()

    def __getitem__(self, key: str):
        self.names.add(key)
        return self.get(key)


def _authorize_reads(action, table, _column, database, _source):
    if action == sqlite3.SQLITE_READ:
        # SQLite can omit the database name when an operation such as COUNT(*) reads no columns.
        if database not in ("main", None) or (table or "").lower() not in ALLOWED_TABLES:
            return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    # A lock should fail promptly so SQLite's busy wait cannot exceed the query deadline.
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=0.0)
    try:
        conn.execute("PRAGMA query_only = ON").close()
        conn.set_authorizer(_authorize_reads)
    except sqlite3.Error:
        conn.close()
        raise
    return conn


def _references_cte(table: exp.Table) -> bool:
    if table.db:
        return False
    name = table.name.lower()
    parent = table.parent
    while parent is not None:
        # SQLGlot versions use either key for the same WITH clause.
        with_clause = parent.args.get("with_") or parent.args.get("with")
        if isinstance(with_clause, exp.With) and any(cte.alias.lower() == name for cte in with_clause.expressions):
            return True
        parent = parent.parent
    return False


def _sqlite_error(error: sqlite3.Error, *, preparing: bool = False) -> SqlError:
    message = str(error)
    detail = message.lower()
    code = getattr(error, "sqlite_errorcode", 0) & 0xFF
    if code == sqlite3.SQLITE_INTERRUPT:
        return SqlError("timeout", TIMEOUT_MESSAGE)
    if code in (sqlite3.SQLITE_AUTH, sqlite3.SQLITE_READONLY) or "one statement at a time" in detail:
        return SqlError("policy", message)
    if detail.startswith(("no such column:", "ambiguous column name:")):
        return SqlError("column", message)
    if isinstance(error, (sqlite3.ProgrammingError, sqlite3.InterfaceError)) and "bind" in detail:
        return SqlError("params", message)
    if preparing and code == sqlite3.SQLITE_ERROR and not detail.startswith("no such table:"):
        return SqlError("syntax", message)
    return SqlError("runtime", message)


def validate(sql: str, params: dict, conn: sqlite3.Connection) -> None:
    """Raise SqlError if the query fails policy, binding or preparation checks."""
    if not isinstance(sql, str) or "\0" in sql:
        raise SqlError("syntax", "A valid SQL string is required.")
    try:
        statements = [
            statement for statement in parse(sql, read="sqlite")
            if statement is not None and not isinstance(statement, exp.Semicolon)
        ]
    except (SqlglotError, RecursionError) as error:
        raise SqlError("syntax", str(error)) from error

    if not statements:
        raise SqlError("syntax", "A SELECT statement is required.")
    if len(statements) != 1 or not isinstance(statements[0], SELECT_STATEMENTS):
        raise SqlError("policy", "Only one SELECT statement is allowed.")
    statement = statements[0]
    if statement.find(exp.DML, exp.DDL, exp.Command, exp.Into) is not None:
        raise SqlError("policy", "Only a read-only SELECT statement is allowed.")
    for table in statement.find_all(exp.Table):
        if (
            not isinstance(table.this, exp.Identifier)
            or table.catalog
            or table.db.lower() not in ("", "main")
            or (table.name.lower() not in ALLOWED_TABLES and not _references_cte(table))
        ):
            raise SqlError("policy", "Queries may only read the sales and products tables.")

    if not isinstance(params, dict) or any(not isinstance(key, str) for key in params):
        raise SqlError("params", "Query parameters must be a dictionary with string keys.")
    bindings = _ParameterBindings(params)
    try:
        conn.execute(f"EXPLAIN {sql}", bindings).close()
    except OverflowError as error:
        raise SqlError("params", str(error)) from error
    except sqlite3.Error as error:
        raise _sqlite_error(error, preparing=True) from error

    missing = bindings.names - params.keys()
    unexpected = params.keys() - bindings.names
    if missing or unexpected:
        differences = []
        if missing:
            differences.append(f"Missing parameters {', '.join(sorted(missing))}.")
        if unexpected:
            differences.append(f"Unexpected parameters {', '.join(sorted(unexpected))}.")
        raise SqlError("params", " ".join(differences))


def run_query(
    sql: str, params: dict, conn: sqlite3.Connection, *, timeout_s: float, max_rows: int
) -> QueryResult:
    """Validate and execute a SELECT under the time limit and row cap."""
    if not isfinite(timeout_s) or max_rows < 0:
        raise SqlError("runtime", "The SQL time limit must be finite and the row limit must be nonnegative.")
    started = perf_counter()
    deadline = started + timeout_s

    def expired() -> bool:
        return perf_counter() >= deadline

    if expired():
        raise SqlError("timeout", TIMEOUT_MESSAGE)
    try:
        conn.set_progress_handler(expired, PROGRESS_INTERVAL)
        try:
            validate(sql, params, conn)
            if expired():
                raise SqlError("timeout", TIMEOUT_MESSAGE)
            with closing(conn.cursor()) as cursor:
                cursor.row_factory = None
                cursor.execute(sql, params)
                columns = [column[0] for column in cursor.description]
                rows = cursor.fetchmany(max_rows + 1)
        finally:
            conn.set_progress_handler(None, 0)
    except sqlite3.Error as error:
        raise _sqlite_error(error) from error

    finished = perf_counter()
    if finished >= deadline:
        raise SqlError("timeout", TIMEOUT_MESSAGE)
    return QueryResult(
        columns=columns,
        rows=rows[:max_rows],
        truncated=len(rows) > max_rows,
        elapsed_ms=(finished - started) * 1000,
    )
