import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest

from eval.templates import answer
from rowsetta.settings import Settings
from tests.test_design import build_sample

COUNTRY_QUESTION = "Mayıs 2011’de Fransa ve Almanya’nın net satışını karşılaştır"


@pytest.fixture(scope="module")
def template_settings(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("method_a") / "rowsetta.sqlite"
    build_sample(db_path)
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute("INSERT INTO products VALUES ('POST', 'POSTAGE', 0)")
        db.execute(
            """INSERT INTO sales(line_id, invoice_no, invoice_at, country, stock_code, net_qty, unit_price_u)
               VALUES (13, '1007', '2011-05-21 15:00:00', 'Spain', 'POST', 1, 1000000)"""
        )
    return Settings(db_path=db_path)


@pytest.mark.parametrize(
    ("question", "columns", "rows", "chart"),
    [
        (COUNTRY_QUESTION, ["country", "net_sales_u"], [("France", 325000), ("Germany", 181250)], "bar"),
        ("MAYIS'TA Fransa’nın toplam cirosu ne kadar?", ["net_sales_u"], [(325000,)], "value"),
        (
            "Mayıs 2011'de net satışı en yüksek 2 ülke hangisi?",
            ["country", "net_sales_u"], [("Spain", 1050000), ("France", 325000)], "bar",
        ),
        (
            "Mayıs 2011'de ürün bazında net satış",
            ["stock_code", "product_name", "net_sales_u"],
            [("A001", "Ceramic mug", 400000), ("B002", "Notebook", 156250)], "bar",
        ),
        (
            "Mayıs 2011'de satılan adet bakımından ilk 1 ürün hangisi?",
            ["stock_code", "product_name", "sold_qty"], [("A001", "Ceramic mug", 18)], "bar",
        ),
        (
            "Mayıs 2011'de stok kodu A001 olan ürünün brüt satış tutarı ne kadar?",
            ["gross_sales_u"], [(450000,)], "value",
        ),
        ("Fransa’nın 2011 aylık net satışları", ["month", "net_sales_u"], [("2011-05", 325000), ("2011-06", 2500000)], "line"),
        (
            "Mayıs 2011'de Almanya’nın günlük iade tutarı",
            ["day", "credit_u"], [("2011-05-02", 0), ("2011-05-22", 31250), ("2011-05-31", 31250)], "line",
        ),
        (
            "Mayıs 2011 ülkelere göre aylık fatura sayısı",
            ["month", "country", "invoice_count"],
            [("2011-05", "France", 2), ("2011-05", "Germany", 2), ("2011-05", "Spain", 1)], "line",
        ),
    ],
)
def test_method_a_templates(template_settings, question, columns, rows, chart):
    result = answer(question, template_settings)
    assert result.status == "ok", result.message
    assert result.columns == columns
    assert result.rows == rows
    assert result.chart == chart
    assert result.attempts == 0
    assert result.model_calls == []


def test_method_a_binds_dates_and_countries_and_obeys_row_cap(template_settings):
    result = answer(COUNTRY_QUESTION, replace(template_settings, max_rows=1))
    assert result.status == "ok", result.message
    assert result.params == {
        "start": "2011-05-01 00:00:00", "end": "2011-06-01 00:00:00", "c1": "France", "c2": "Germany",
    }
    assert result.rows == [("France", 325000)]
    assert result.truncated


def test_method_a_preserves_sql_and_headers_for_an_empty_result(template_settings):
    result = answer(COUNTRY_QUESTION.replace("2011", "2012"), template_settings)
    assert result.status == "empty"
    assert result.sql
    assert result.columns == ["country", "net_sales_u"]
    assert result.rows == []


@pytest.mark.parametrize("question", [
    "Aralık ayındaki net satış ne kadar?",
    "Mayıs ve Haziran net satışlarını karşılaştır",
    "Mayıs 2011 Atlantis’in net satışı ne kadar?",
    "Fransa hariç net satış ne kadar?",
    "En çok satan 3 ürün hangileri?",
    "Kâr marjı en yüksek ürün hangisi?",
])
def test_method_a_returns_an_error_for_questions_outside_its_templates(template_settings, question):
    settings = replace(template_settings, db_path=template_settings.db_path.with_name("not_opened.sqlite"))
    result = answer(question, settings)
    assert result.status == "error"
    assert result.sql is None
    assert result.attempts == 0
