"""Data design and SQL execution checks on a 12-row synthetic fixture.

The data checks are adapted from the GPT design package.
Covers signed quantities, half-open month boundaries, product label selection,
join cardinality, rounding after aggregation, empty results and the read-only
connection. Run: python -m pytest -q
"""

from __future__ import annotations

import csv
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from rowsetta.present import units_to_gbp
from rowsetta.sql import connect_readonly, run_query, validate
from rowsetta.types import SqlError

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCALE = Decimal(10000)
MAY = {
    "start_at": "2011-05-01 00:00:00",
    "end_at": "2011-06-01 00:00:00",
    "first_country": "France",
    "second_country": "Germany",
}


def build_sample(db_path: Path) -> tuple[int, Counter]:
    with (FIXTURES / "retail_fixture.csv").open(encoding="utf-8", newline="") as fixture:
        raw = list(csv.DictReader(fixture))
    products: dict[str, tuple] = {}
    sales = []
    rejected: Counter = Counter()
    for line_id, row in enumerate(raw, start=1):
        qty = int(row["quantity"])
        price = Decimal(row["unit_price_gbp"])
        if not qty:
            rejected["zero quantity"] += 1
            continue
        if price <= 0 or price * SCALE != (price * SCALE).to_integral_value():
            rejected["invalid price"] += 1
            continue
        code = row["stock_code"]
        date = datetime.fromisoformat(row["invoice_at"]).isoformat(sep=" ")
        products.setdefault(code, ("", 0, None))
        if row["description"] and (date, line_id) > products[code][:2]:
            products[code] = (date, line_id, row["description"])
        invoice_no = row["invoice_no"]
        net_qty = -abs(qty) if invoice_no.upper().startswith("C") or qty < 0 else qty
        sales.append((line_id, invoice_no, date, row["country"], code, net_qty, int(price * SCALE)))

    schema_sql = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    with closing(sqlite3.connect(db_path)) as db, db:
        db.executescript(schema_sql)
        db.executemany(
            "INSERT INTO products(stock_code, product_name) VALUES (?, ?)",
            [(code, label[2]) for code, label in products.items()],
        )
        db.executemany(
            "INSERT INTO sales(line_id, invoice_no, invoice_at, country, stock_code, net_qty, unit_price_u) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            sales,
        )
    return len(raw), rejected


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "sample.sqlite"
    raw_count, rejected = build_sample(path)
    with closing(connect_readonly(path)) as db:
        yield db, raw_count, rejected


@pytest.fixture(scope="module")
def query() -> str:
    return (FIXTURES / "country_net.sql").read_text(encoding="utf-8")


def test_source_and_accepted_counts(sample):
    db, raw_count, rejected = sample
    count = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    assert (raw_count, count) == (12, 10)
    assert dict(rejected) == {"invalid price": 1, "zero quantity": 1}


def test_may_net_amounts_in_units(sample, query):
    db, *_ = sample
    assert db.execute(query, MAY).fetchall() == [("France", 325000), ("Germany", 181250)]


def test_round_after_aggregation(sample, query):
    db, *_ = sample
    totals = [(c, str(units_to_gbp(u))) for c, u in db.execute(query, MAY).fetchall()]
    assert totals == [("France", "32.50"), ("Germany", "18.13")]


def test_credit_signs_for_all_three_patterns(sample):
    db, *_ = sample
    rows = db.execute("SELECT line_id, net_qty FROM sales WHERE net_qty < 0 ORDER BY line_id").fetchall()
    assert rows == [(3, -2), (6, -1), (10, -1)]


def test_month_boundary_membership(sample):
    db, *_ = sample
    rows = db.execute(
        "SELECT line_id FROM sales WHERE line_id IN (1, 5, 7, 8) "
        "AND invoice_at >= :start_at AND invoice_at < :end_at ORDER BY line_id",
        MAY,
    ).fetchall()
    assert rows == [(1,), (5,)]


def test_product_label_and_join_cardinality(sample):
    db, *_ = sample
    label = db.execute("SELECT product_name FROM products WHERE stock_code = 'A001'").fetchone()
    joined = db.execute("SELECT COUNT(*) FROM sales JOIN products USING(stock_code)").fetchone()[0]
    assert (label, joined) == (("Ceramic mug",), 10)


def test_is_product_defaults_to_one(sample):
    db, *_ = sample
    assert db.execute("SELECT DISTINCT is_product FROM products").fetchall() == [(1,)]


def test_empty_grouping_result(sample, query):
    db, *_ = sample
    params = {**MAY, "first_country": "Italy", "second_country": "Portugal"}
    assert db.execute(query, params).fetchall() == []


def test_read_only_connection_rejects_writes(sample):
    db, *_ = sample
    with pytest.raises(sqlite3.OperationalError):
        db.execute("UPDATE products SET product_name = 'Sample' WHERE stock_code = 'A001'")


@pytest.mark.parametrize(("max_rows", "truncated"), [(1, True), (2, False)])
def test_run_country_net_applies_row_cap_after_aggregation(sample, query, max_rows, truncated):
    db, *_ = sample
    result = run_query(query, MAY, db, timeout_s=3, max_rows=max_rows)
    assert result.columns == ["country", "net_sales_u"]
    assert result.rows == [("France", 325000), ("Germany", 181250)][:max_rows]
    assert result.truncated is truncated
    assert result.elapsed_ms >= 0


def test_run_preserves_columns_for_empty_results(sample, query):
    db, *_ = sample
    params = {**MAY, "first_country": "Spain", "second_country": "Italy", "start_at": "2011-05-22 00:00:00"}
    result = run_query(query, params, db, timeout_s=3, max_rows=200)
    assert result.columns == ["country", "net_sales_u"]
    assert result.rows == []
    assert not result.truncated


def test_run_cte_with_named_bindings_and_count(sample):
    db, *_ = sample
    sql = """
        WITH summary AS (SELECT COUNT(*) AS n FROM main.SALES)
        SELECT n, :label AS label, @label AS repeated, $marker AS marker, ':literal' AS text
        FROM Summary; -- :comment
    """
    result = run_query(sql, {"label": "rows", "marker": "count"}, db, timeout_s=3, max_rows=200)
    assert result.rows == [(10, "rows", "rows", "count", ":literal")]


@pytest.mark.parametrize(
    ("sql", "params", "kind"),
    [
        ("SELECT country FROM", {}, "syntax"),
        ("SELECT missing_column FROM sales", {}, "column"),
        ("SELECT * FROM sqlite_schema", {}, "policy"),
        ("WITH disallowed AS (SELECT * FROM sqlite_schema) SELECT 1", {}, "policy"),
        ("SELECT country FROM sales; SELECT stock_code FROM products", {}, "policy"),
        ("SELECT :country", {}, "params"),
        ("SELECT :country", {"country": "France", "extra": 1}, "params"),
        ("SELECT ?", {}, "params"),
    ],
)
def test_validate_classifies_invalid_queries(sample, sql, params, kind):
    db, *_ = sample
    with pytest.raises(SqlError) as failure:
        validate(sql, params, db)
    assert failure.value.kind == kind


def test_run_rejects_writes_before_sqlite_execution(sample):
    db, *_ = sample
    with pytest.raises(SqlError) as failure:
        run_query("DELETE FROM sales", {}, db, timeout_s=3, max_rows=200)
    assert failure.value.kind == "policy"
    assert db.execute("PRAGMA query_only").fetchone() == (1,)
    assert db.execute("SELECT COUNT(*) FROM sales").fetchone() == (10,)


def test_run_times_out_and_clears_the_progress_handler(sample):
    db, *_ = sample
    series = """
        WITH RECURSIVE numbers(n) AS (
            SELECT 1 UNION ALL SELECT n + 1 FROM numbers WHERE n < :stop
        )
        SELECT SUM(n) AS total FROM numbers
    """
    with pytest.raises(SqlError) as failure:
        run_query(series, {"stop": 10_000_000}, db, timeout_s=0.02, max_rows=200)
    assert failure.value.kind == "timeout"
    assert db.execute(series, {"stop": 1000}).fetchone() == (500500,)
