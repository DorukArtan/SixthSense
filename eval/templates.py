"""Method A - keyword-matched SQL templates, no LLM (baseline for R5).

Owner: Mehmet Doruk Artan
Cover 8-10 common question shapes (total by country and period, top-N products,
monthly trend ...). Questions outside the templates return status "error".
Uses the same sql.run_query executor as the LLM methods.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime
from time import perf_counter
from typing import TypeVar

from rowsetta.linking import load_glossary
from rowsetta.settings import Settings
from rowsetta.sql import connect_readonly, run_query
from rowsetta.types import Answer, ChartKind, SqlError

MEASURES = {
    "net_sales": ("SUM(s.net_u)", "net_sales_u"),
    "gross_sales": ("SUM(s.gross_u)", "gross_sales_u"),
    "credit": ("SUM(s.credit_u)", "credit_u"),
    "sold_qty": ("SUM(s.sold_qty)", "sold_qty"),
    "invoice_count": ("COUNT(DISTINCT CASE WHEN s.net_qty > 0 THEN s.invoice_no END)", "invoice_count"),
}

COUNTRY_TOTALS = (
    "SELECT s.country AS country, {measure} AS {column}\n"
    "FROM sales AS s{where}\nGROUP BY s.country\nORDER BY {column} DESC, s.country ASC"
)
PRODUCT_SALES = "FROM sales AS s JOIN products AS p ON s.stock_code = p.stock_code"
PRODUCT_TOTALS = (
    "SELECT p.stock_code, COALESCE(NULLIF(p.product_name, ''), p.stock_code) AS product_name, {measure} AS {column}\n"
    + PRODUCT_SALES + "{where}\nGROUP BY p.stock_code, p.product_name\nORDER BY {column} DESC, p.stock_code ASC"
)
TEMPLATES: dict[str, tuple[str, ChartKind]] = {
    "total": ("SELECT {measure} AS {column}\nFROM sales AS s{where}", "value"),
    "by_country": (COUNTRY_TOTALS, "bar"),
    "country_ranking": (COUNTRY_TOTALS + "\nLIMIT :row_limit", "bar"),
    "by_product": (PRODUCT_TOTALS, "bar"),
    "product_ranking": (PRODUCT_TOTALS + "\nLIMIT :row_limit", "bar"),
    "product_total": ("SELECT {measure} AS {column}\n" + PRODUCT_SALES + "{where}", "value"),
    "monthly": (
        "SELECT SUBSTR(s.invoice_at, 1, 7) AS month, {measure} AS {column}\n"
        "FROM sales AS s{where}\nGROUP BY month\nORDER BY month ASC",
        "line",
    ),
    "daily": (
        "SELECT SUBSTR(s.invoice_at, 1, 10) AS day, {measure} AS {column}\n"
        "FROM sales AS s{where}\nGROUP BY day\nORDER BY day ASC",
        "line",
    ),
    "monthly_by_country": (
        "SELECT SUBSTR(s.invoice_at, 1, 7) AS month, s.country AS country, {measure} AS {column}\n"
        "FROM sales AS s{where}\nGROUP BY month, s.country\nORDER BY month ASC, s.country ASC",
        "line",
    ),
}

DIMENSION_TERMS = {
    "ülke bazında": "country", "ülkelere göre": "country", "ülke": "country",
    "ürün bazında": "product", "ürünlere göre": "product", "ürün": "product",
    "aylık": "month", "ay ay": "month", "aylara göre": "month", "ay bazında": "month",
    "günlük": "day", "gün gün": "day", "günlere göre": "day", "gün bazında": "day",
    "karşılaştır": "compare", "karşılaştırır": "compare", "karşılaştırma": "compare",
}
GROUPED_TEMPLATES = {
    frozenset(): "total",
    frozenset({"country"}): "by_country",
    frozenset({"product"}): "by_product",
    frozenset({"month"}): "monthly",
    frozenset({"day"}): "daily",
    frozenset({"month", "country"}): "monthly_by_country",
}
RANKED_TEMPLATES = {frozenset({"country"}): "country_ranking", frozenset({"product"}): "product_ranking"}
PRODUCT_TEMPLATES = frozenset({"by_product", "product_ranking", "product_total"})
CONNECTING_WORDS = frozenset({
    "ve", "ile", "icin", "ait", "gore", "olarak", "bakimindan", "olan", "sahip", "yapilan", "satildi",
    "ay", "ayi", "ayinda", "yil", "yili", "yilinda", "tarihinde", "toplam", "toplami", "toplamda",
    "tutar", "tutari", "tutarini", "ne", "kadar", "nedir", "kactir", "hangi", "hangisi", "hangileri",
    "goster", "listele", "hesapla", "oldu", "olmus", "ver", "misin", "bazinda", "gbp",
})

# After folding Turkish letters, accept the common inflections of known terms.
INFLECTION = (
    r"(?:i|u|a|e|in|un|ini|unu|inin|unun|si|su|sini|sunu|sinin|sunun|nin|nun|ni|nu|na|ne|ya|ye|yi|yu|"
    r"da|de|ta|te|nda|nde|daki|deki|taki|teki|ndaki|ndeki|dan|den|tan|ten|ndan|nden|la|le|yla|yle|"
    r"lar|ler|lari|leri|larin|lerin|lara|lere|larina|lerine|larini|lerini|larinin|lerinin)"
)
SUFFIX = rf"(?:'?{INFLECTION})?"
YEAR = re.compile(rf"(?<!\w)([0-9]{{4}}){SUFFIX}(?!\w)")
RANKING = re.compile(r"\b(?:en (?:yuksek|fazla|cok(?: satan| satilan)?)|ilk|top)(?: ([0-9]+))?(?!\w)")
STOCK_CODE = re.compile(
    rf"(?<!\w)(?:(?:stok|urun) kodu ([a-z0-9][a-z0-9_-]*)|([0-9]{{5}}[a-z]*)){SUFFIX}(?!\w)"
)

T = TypeVar("T")


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold().replace("ı", "i").replace("’", "'"))
    unaccented = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(unaccented.split())


def _consume_terms(text: str, aliases: dict[str, T]) -> tuple[str, list[T]]:
    if not aliases:
        return text, []
    normalized = {_normalize(term): value for term, value in aliases.items()}
    alternatives = "|".join(re.escape(term) for term in sorted(normalized, key=len, reverse=True))
    matches = []

    def take(match: re.Match[str]) -> str:
        matches.append(normalized[match[1]])
        return " "

    remaining = re.sub(rf"(?<!\w)({alternatives}){SUFFIX}(?!\w)", take, text)
    return " ".join(remaining.split()), matches


def _month_range(year: int, month: int) -> tuple[datetime, datetime]:
    if month == 12:
        return datetime(year, 12, 1), datetime(year + 1, 1, 1)
    return datetime(year, month, 1), datetime(year, month + 1, 1)


def _period_params(months: list[int], years: list[int], dataset_range: list[str]) -> dict[str, str] | None:
    if len(months) > 1 or len(years) > 1 or any(not 1 <= year < 9999 for year in years):
        return None
    if months:
        month = months[0]
        if not years:
            first, last = map(datetime.fromisoformat, dataset_range)
            candidates = (_month_range(year, month) for year in range(first.year, last.year + 1))
            periods = [(start, end) for start, end in candidates if start < last and end > first]
            if len(periods) != 1:
                return None
            start, end = periods[0]
        else:
            start, end = _month_range(years[0], month)
    elif years:
        start, end = datetime(years[0], 1, 1), datetime(years[0] + 1, 1, 1)
    else:
        return {}
    return {"start": start.isoformat(sep=" "), "end": end.isoformat(sep=" ")}


def _pick_template(dimensions: frozenset[str], n_countries: int, stock_code: str | None, limit: int | None) -> str | None:
    if "compare" in dimensions:
        if n_countries >= 2 and dimensions <= {"compare", "country"} and stock_code is None and limit is None:
            return "by_country"
        return None
    if stock_code:
        if dimensions <= {"product"} and limit is None:
            return "product_total"
        return None
    if limit is not None:
        return RANKED_TEMPLATES.get(dimensions)
    if not dimensions and n_countries > 1:
        return None
    return GROUPED_TEMPLATES.get(dimensions)


def _compile_question(question: str, glossary: dict) -> tuple[str, dict[str, str | int], ChartKind] | None:
    text = _normalize(question)
    rankings = RANKING.findall(text)
    if len(rankings) > 1:
        return None
    limit = None
    if rankings:
        count = rankings[0] or "1"
        if len(count) > 19 or not 0 < int(count) < 2**63:
            return None
        limit = int(count)
        text = RANKING.sub(" ", text)

    stock_codes = STOCK_CODE.findall(text)
    if len(stock_codes) > 1:
        return None
    stock_code = None
    if stock_codes:
        explicit_code, bare_code = stock_codes[0]
        stock_code = explicit_code or bare_code
    text = STOCK_CODE.sub(" ", text)
    metric_aliases = {term: key for key in MEASURES for term in glossary["metrics"].get(key, ())}
    text, metrics = _consume_terms(text, metric_aliases)
    if len(set(metrics)) != 1:
        return None

    countries = glossary["countries"]
    country_aliases = {**{value: value for value in countries.values()}, **countries}
    text, matched_countries = _consume_terms(text, country_aliases)
    country_values = list(dict.fromkeys(matched_countries))
    text, months = _consume_terms(text, glossary["months"])
    years = [int(year) for year in YEAR.findall(text)]
    text, dimensions = _consume_terms(YEAR.sub(" ", text), DIMENSION_TERMS)

    # Reject unrecognized constraints instead of broadening the query silently.
    if set(re.findall(r"\w+", text)) - CONNECTING_WORDS:
        return None
    template = _pick_template(frozenset(dimensions), len(country_values), stock_code, limit)
    period = _period_params(months, years, glossary["dataset_range"])
    if template is None or period is None:
        return None

    params: dict[str, str | int] = dict(period)
    filters = []
    if period:
        filters.append("s.invoice_at >= :start AND s.invoice_at < :end")
    if country_values:
        country_params = {f"c{index}": value for index, value in enumerate(country_values, start=1)}
        params.update(country_params)
        placeholders = ", ".join(f":{name}" for name in country_params)
        filters.append(f"s.country IN ({placeholders})")
    if template in PRODUCT_TEMPLATES:
        filters.append("p.is_product = 1")
    if stock_code is not None:
        filters.append("p.stock_code = :stock_code COLLATE NOCASE")
        params["stock_code"] = stock_code.upper()
    if limit is not None:
        params["row_limit"] = limit

    where = "\nWHERE " + " AND ".join(filters) if filters else ""
    measure, column = MEASURES[metrics[0]]
    sql, chart = TEMPLATES[template]
    return sql.format(measure=measure, column=column, where=where), params, chart


def answer(question: str, settings: Settings) -> Answer:
    """Match a Turkish question and execute the resulting SQL without a model call."""
    started = perf_counter()
    try:
        matched = _compile_question(question, load_glossary(settings.glossary_path))
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return Answer(
            "error", question, message="Yöntem A sözlüğü okunamadı.",
            timings_ms={"total": (perf_counter() - started) * 1000},
        )
    timings = {"linking": (perf_counter() - started) * 1000}
    if matched is None:
        timings["total"] = (perf_counter() - started) * 1000
        return Answer("error", question, message="Soru Yöntem A’nın SQL şablonlarına uymuyor.", timings_ms=timings)

    sql, params, chart = matched
    try:
        with closing(connect_readonly(settings.db_path)) as connection:
            result = run_query(sql, params, connection, timeout_s=settings.sql_timeout_s, max_rows=settings.max_rows)
    except (SqlError, sqlite3.Error) as error:
        timings["total"] = (perf_counter() - started) * 1000
        message = error.message if isinstance(error, SqlError) else str(error)
        return Answer("error", question, sql=sql, params=params, message=message, timings_ms=timings)

    timings.update(sql=result.elapsed_ms, total=(perf_counter() - started) * 1000)
    return Answer(
        status="ok" if result.rows else "empty",
        question=question,
        sql=sql,
        params=params,
        columns=result.columns,
        rows=result.rows,
        truncated=result.truncated,
        chart=chart if result.rows else None,
        message=None if result.rows else "Bu filtrelerle kayıt bulunamadı.",
        timings_ms=timings,
    )
