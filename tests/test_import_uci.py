import csv
import hashlib
import json
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from rowsetta.sql import connect_readonly
from scripts import import_uci

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_import_workbook_and_reconcile_rows(tmp_path, monkeypatch):
    source = tmp_path / "Online Retail.xlsx"
    config = tmp_path / "non_product_codes.json"
    db_path = tmp_path / "data" / "rowsetta.sqlite"
    config.write_text(json.dumps({"codes": ["POST"]}), encoding="utf-8")
    monkeypatch.setattr(import_uci, "DB_PATH", db_path)
    monkeypatch.setattr(import_uci, "NON_PRODUCT_CONFIG", config)

    workbook = Workbook()
    sheet = workbook.active
    sheet.append((
        "InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice", "CustomerID", "Country",
    ))
    with (FIXTURES / "retail_fixture.csv").open(encoding="utf-8", newline="") as fixture:
        for row in csv.DictReader(fixture):
            sheet.append((
                row["invoice_no"], row["stock_code"], row["description"], int(row["quantity"]),
                datetime.fromisoformat(row["invoice_at"]), float(row["unit_price_gbp"]), 10001, row["country"],
            ))
    june = datetime(2011, 6, 2)
    postage = ("000013", "POST", "POSTAGE", 1, june, 2.55, 10001, "France")
    sheet.append(postage)
    sheet.append(postage)
    sheet.append(("A0014", "B002", "Bad debt", 1, june, 2.55, 10001, "France"))
    sheet.append(("0015", "B002", "Too many decimals", 1, june, 0.00001, 10001, "France"))
    sheet.append(("0016", "B002", "Missing country", 1, june, 2.55, 10001, None))
    workbook.save(source)

    assert import_uci.main(source) == 0

    report = json.loads(db_path.with_name("import_report.json").read_text(encoding="utf-8"))
    assert (report["raw_rows"], report["accepted_rows"], report["rejected_rows"]) == (17, 12, 5)
    assert report["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report["rejections_by_reason"] == {
        "bad_debt_adjustment": 1,
        "missing_required_field": 1,
        "non_positive_price": 1,
        "price_precision": 1,
        "zero_quantity": 1,
    }
    assert report["non_product_codes"] == ["POST"]
    assert {row["stock_code"] for row in report["unusual_stock_codes"]} == {"A001", "B002", "POST"}

    with closing(connect_readonly(db_path)) as db:
        query = (FIXTURES / "country_net.sql").read_text(encoding="utf-8")
        may = {
            "start_at": "2011-05-01 00:00:00",
            "end_at": "2011-06-01 00:00:00",
            "first_country": "France",
            "second_country": "Germany",
        }
        assert db.execute(query, may).fetchall() == [("France", 325000), ("Germany", 181250)]
        assert db.execute("SELECT product_name FROM products WHERE stock_code = 'A001'").fetchone() == (
            "Ceramic mug",
        )
        assert db.execute("SELECT is_product FROM products WHERE stock_code = 'POST'").fetchone() == (0,)
        assert db.execute("SELECT invoice_no, unit_price_u FROM sales WHERE stock_code = 'POST'").fetchall() == [
            ("000013", 25500), ("000013", 25500),
        ]


def test_publication_restores_report_if_database_cannot_be_replaced(tmp_path, monkeypatch):
    db_path = tmp_path / "rowsetta.sqlite"
    report_path = tmp_path / "import_report.json"
    db_path.write_bytes(b"previous snapshot")
    report_path.write_bytes(b"previous report")
    staging = tmp_path / "staging"
    staging.mkdir()
    staged_db = staging / db_path.name
    staged_report = staging / report_path.name
    staged_db.write_bytes(b"new snapshot")
    staged_report.write_bytes(b"new report")

    replace_file = Path.replace

    def replace(path, target):
        if path == staged_db:
            raise PermissionError("database is open")
        return replace_file(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(PermissionError, match="database is open"):
        import_uci.publish_snapshot(staged_db, staged_report, db_path)

    assert db_path.read_bytes() == b"previous snapshot"
    assert report_path.read_bytes() == b"previous report"
