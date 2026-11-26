"""Build data/rowsetta.sqlite from the UCI Online Retail workbook.

Owner: Mehmet Doruk Artan
Usage: python scripts/import_uci.py [path/to/Online Retail.xlsx]

Rules (docs/architecture.md, "Aktarım kuralları"):
 1. Read with pandas.read_excel; convert prices with Decimal(str(x)), never Decimal(x).
 2. Invoice starting with "C" or negative quantity -> net_qty = -abs(quantity).
 3. Drop invoices starting with "A" (Adjust bad debt), including the positive one.
 4. Drop zero quantity, non-positive price, price not representable in 4 decimals,
    missing required fields; count each reason.
 5. List stock codes outside the usual pattern (5 digits + optional letters) so the
    owner can classify them into config/non_product_codes.json (is_product = 0).
 6. product_name = latest non-empty description among accepted lines.
 7. Do not import CustomerID.
 8. Write data/import_report.json: raw / accepted / rejected counts by reason,
    SHA-256 of the source file, rule version.
Build into a temporary file and replace the snapshot only after the checks pass.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from argparse import ArgumentParser
from collections import Counter
from contextlib import closing
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import NamedTuple
from zipfile import BadZipFile

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "data" / "raw" / "Online Retail.xlsx"
DB_PATH = ROOT / "data" / "rowsetta.sqlite"
SCHEMA = ROOT / "db" / "schema.sql"
NON_PRODUCT_CONFIG = ROOT / "config" / "non_product_codes.json"
RULE_VERSION = "0.1"
SOURCE_COLUMNS = (
    "InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice", "Country",
)
PRODUCT_CODE = re.compile(r"[0-9]{5}[A-Za-z]*")
UNITS_PER_GBP = 10_000
PRICE_INCREMENT = Decimal("0.0001")
SQLITE_MAX_INT = 2**63 - 1
MAX_UNIT_PRICE = Decimal(SQLITE_MAX_INT) / UNITS_PER_GBP


class SaleLine(NamedTuple):
    line_id: int
    invoice_no: str
    invoice_at: str
    country: str
    stock_code: str
    net_qty: int
    unit_price_u: int


class RejectedRow(ValueError):
    """A source row with a reportable reason for exclusion."""


def cell_text(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip()


def normalize_line(line_id: int, cells: tuple[object, ...]) -> tuple[SaleLine, str]:
    invoice_no, stock_code, description, quantity_text, date_text, price_text, country = map(cell_text, cells)
    invoice_prefix = invoice_no[:1].upper()
    if invoice_prefix == "A":
        raise RejectedRow("bad_debt_adjustment")
    if not all((invoice_no, stock_code, quantity_text, date_text, price_text, country)):
        raise RejectedRow("missing_required_field")

    try:
        invoice_at = datetime.fromisoformat(date_text)
    except ValueError as error:
        raise RejectedRow("invalid_date") from error
    if invoice_at.tzinfo is not None:
        raise RejectedRow("invalid_date")

    try:
        quantity = Decimal(quantity_text)
    except InvalidOperation as error:
        raise RejectedRow("invalid_quantity") from error
    if not quantity.is_finite() or not -SQLITE_MAX_INT <= quantity <= SQLITE_MAX_INT:
        raise RejectedRow("invalid_quantity")
    if quantity != quantity.to_integral_value():
        raise RejectedRow("invalid_quantity")
    if not quantity:
        raise RejectedRow("zero_quantity")
    net_qty = -abs(int(quantity)) if invoice_prefix == "C" else int(quantity)

    try:
        price = Decimal(price_text)
    except InvalidOperation as error:
        raise RejectedRow("invalid_price") from error
    if not price.is_finite():
        raise RejectedRow("invalid_price")
    if price <= 0:
        raise RejectedRow("non_positive_price")
    if price > MAX_UNIT_PRICE:
        raise RejectedRow("amount_out_of_range")
    if price != price.quantize(PRICE_INCREMENT):
        raise RejectedRow("price_precision")
    unit_price_u = int(price * UNITS_PER_GBP)
    if abs(net_qty) * unit_price_u > SQLITE_MAX_INT:
        raise RejectedRow("amount_out_of_range")

    sale = SaleLine(
        line_id, invoice_no, invoice_at.isoformat(sep=" "), country, stock_code, net_qty, unit_price_u,
    )
    return sale, description


def load_non_product_codes() -> set[str]:
    config = json.loads(NON_PRODUCT_CONFIG.read_text(encoding="utf-8"))
    codes = config.get("codes") if isinstance(config, dict) else None
    if not isinstance(codes, list) or any(not isinstance(code, str) or not code.strip() for code in codes):
        raise ValueError(f"Expected a list of non-empty stock codes in {NON_PRODUCT_CONFIG}")
    return {code.strip() for code in codes}


def build_snapshot(
    path: Path,
    sales: list[SaleLine],
    products: dict[str, tuple[str, str | None]],
    non_product_codes: set[str],
) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA.read_text(encoding="utf-8"))
        with db:
            db.executemany(
                "INSERT INTO products(stock_code, product_name, is_product) VALUES (?, ?, ?)",
                ((code, name, int(code not in non_product_codes)) for code, (_, name) in products.items()),
            )
            db.executemany(
                """INSERT INTO sales(line_id, invoice_no, invoice_at, country, stock_code, net_qty, unit_price_u)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                sales,
            )
        if db.execute("SELECT COUNT(*) FROM sales").fetchone() != (len(sales),):
            raise sqlite3.DatabaseError("The snapshot row count does not match the accepted row count")
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise sqlite3.DatabaseError("SQLite integrity check failed")


def publish_snapshot(staged_db: Path, staged_report: Path, db_path: Path) -> None:
    report_path = db_path.with_name(staged_report.name)
    previous_report = staged_report.with_suffix(".backup")
    # Serialize publication across imports. Closing the connection releases the OS lock.
    with closing(sqlite3.connect(db_path.parent / ".import.lock")) as lock:
        lock.execute("BEGIN EXCLUSIVE")
        if report_path.exists():
            copyfile(report_path, previous_report)
        staged_report.replace(report_path)
        try:
            staged_db.replace(db_path)
        except OSError:
            # For example, Windows can refuse to replace a database open in another process.
            if previous_report.exists():
                previous_report.replace(report_path)
            else:
                report_path.unlink()
            raise


def main(source: Path = DEFAULT_SOURCE) -> int:
    non_product_codes = load_non_product_codes()
    workbook = source.read_bytes()
    data = pd.read_excel(
        BytesIO(workbook),
        engine="openpyxl",
        usecols=lambda column: column in SOURCE_COLUMNS,
        dtype=object,
        keep_default_na=False,
    )
    missing_columns = set(SOURCE_COLUMNS).difference(data.columns)
    if missing_columns:
        raise ValueError(f"Missing workbook columns: {', '.join(sorted(missing_columns))}")

    rejected: Counter[str] = Counter()
    products: dict[str, tuple[str, str | None]] = {}
    sales: list[SaleLine] = []
    for line_id, cells in enumerate(data[list(SOURCE_COLUMNS)].itertuples(index=False, name=None), start=1):
        try:
            sale, description = normalize_line(line_id, cells)
        except RejectedRow as error:
            rejected[str(error)] += 1
            continue
        sales.append(sale)
        last_date, _ = products.setdefault(sale.stock_code, ("", None))
        if description and sale.invoice_at >= last_date:
            products[sale.stock_code] = sale.invoice_at, description

    if not sales:
        raise ValueError(f"No sales rows accepted from {source.name} ({len(data)} rows read)")
    rejection_count = sum(rejected.values())
    if len(data) != len(sales) + rejection_count:
        raise ValueError("Accepted and rejected rows do not reconcile with the source")
    report = {
        "source_file": source.name,
        "source_sha256": hashlib.sha256(workbook).hexdigest(),
        "rule_version": RULE_VERSION,
        "raw_rows": len(data),
        "accepted_rows": len(sales),
        "rejected_rows": rejection_count,
        "rejections_by_reason": dict(sorted(rejected.items())),
        "product_rows": len(products),
        "duplicate_rows_preserved": True,
        "non_product_codes": sorted(non_product_codes.intersection(products)),
        "unusual_stock_codes": [
            {"stock_code": code, "product_name": name}
            for code, (_, name) in sorted(products.items())
            if not PRODUCT_CODE.fullmatch(code)
        ],
    }

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".import-uci-", dir=DB_PATH.parent) as staging_dir:
        staged_db = Path(staging_dir) / DB_PATH.name
        staged_report = Path(staging_dir) / "import_report.json"
        build_snapshot(staged_db, sales, products, non_product_codes)
        staged_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        publish_snapshot(staged_db, staged_report, DB_PATH)

    print(f"Imported {len(sales):,} of {len(data):,} rows into {DB_PATH} ({rejection_count:,} rejected)")
    return 0


if __name__ == "__main__":
    parser = ArgumentParser(description="Import UCI Online Retail into the Rowsetta SQLite snapshot.")
    parser.add_argument("source", type=Path, nargs="?", default=DEFAULT_SOURCE, help="path to Online Retail.xlsx")
    try:
        raise SystemExit(main(parser.parse_args().source))
    except (OSError, ValueError, sqlite3.Error, BadZipFile) as error:
        parser.exit(1, f"Import failed: {error}\n")
