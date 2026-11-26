"""Shared contracts between Rowsetta modules.

Every module talks to the others only through these types. Freeze this file on
27 November; announce any change to the team before merging it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Metric = Literal["net_sales", "gross_sales", "credit", "sold_qty", "invoice_count"]
ResponseKind = Literal["query", "clarify", "unsupported"]
AnswerStatus = Literal["ok", "empty", "clarify", "unsupported", "error"]
ChartKind = Literal["bar", "line", "value"]
SqlErrorKind = Literal["syntax", "column", "policy", "params", "timeout", "runtime"]

# SQL errors the model may get one chance to repair. Policy and timeout
# rejections end the attempt (see docs/architecture.md, "Sorgu akışı").
REPAIRABLE_ERRORS: frozenset[str] = frozenset({"syntax", "column", "params"})


@dataclass
class LinkedQuestion:
    """Output of linking.py: the Turkish question mapped onto the schema."""

    text: str
    metric: Metric | None = None
    countries: list[str] = field(default_factory=list)  # stored values: "France", "EIRE"
    period: tuple[str, str] | None = None  # [start, end) as "YYYY-MM-DD HH:MM:SS"
    product_hints: list[str] = field(default_factory=list)  # stock codes or English names
    ambiguities: list[str] = field(default_factory=list)  # e.g. "metric", "period"


@dataclass
class ModelResponse:
    """Parsed model output. model.py must validate it against MODEL_RESPONSE_SCHEMA."""

    kind: ResponseKind
    sql: str | None = None
    params: dict[str, str | int] = field(default_factory=dict)
    metric: Metric | None = None
    message: str | None = None  # one Turkish sentence for clarify / unsupported


@dataclass
class ModelCall:
    """Bookkeeping for one model call, used by eval/run.py for latency and cost."""

    backend: str  # "ollama" or "gemini"
    model: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class QueryResult:
    """Output of sql.run_query when the query executed."""

    columns: list[str]
    rows: list[tuple]
    truncated: bool  # True when more than MAX_ROWS rows exist
    elapsed_ms: float


@dataclass
class SqlError(Exception):
    """Raised by sql.validate / sql.run_query."""

    kind: SqlErrorKind
    message: str

    @property
    def repairable(self) -> bool:
        return self.kind in REPAIRABLE_ERRORS


@dataclass
class Answer:
    """Output of pipeline.answer, rendered by app.py and scored by eval/run.py."""

    status: AnswerStatus
    question: str
    sql: str | None = None
    params: dict = field(default_factory=dict)
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    truncated: bool = False
    chart: ChartKind | None = None
    message: str | None = None
    attempts: int = 0  # model calls used: 1, or 2 after a repair
    model_calls: list[ModelCall] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)  # linking, model, sql, total


# JSON schema for structured output (Ollama `format=` / Gemini response schema).
MODEL_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["query", "clarify", "unsupported"]},
        "sql": {"type": ["string", "null"]},
        "params": {
            "type": "object",
            "additionalProperties": {"type": ["string", "integer"]},
        },
        "metric": {
            "type": ["string", "null"],
            "enum": ["net_sales", "gross_sales", "credit", "sold_qty", "invoice_count", None],
        },
        "message": {"type": ["string", "null"]},
    },
    "required": ["kind", "sql", "params", "metric", "message"],
    "additionalProperties": False,
}
