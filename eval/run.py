"""Run methods A-E on eval/questions.jsonl and write eval/results/*.csv.

Owner: Mehmet Doruk Artan
Usage: python eval/run.py --method D [--questions eval/questions.jsonl]

Per question record: id, method, status, correct, attempts, model calls,
input/output tokens, latency per stage, prompt version, model id, dataset checksum.
Gold results come from running gold_sql on the same snapshot.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT = Path(__file__).resolve().parent.parent
if not __package__:
    sys.path.insert(0, str(ROOT))

from rowsetta.settings import Settings
from rowsetta.sql import connect_readonly, run_query
from rowsetta.types import Answer, QueryResult, ResponseKind, SqlError

QUESTIONS_PATH = ROOT / "eval" / "questions.jsonl"
RESULTS_DIR = ROOT / "eval" / "results"
METHODS = ("A", "B", "C", "D", "E")
RESULT_COLUMNS = (
    "id", "method", "category", "question", "expected_kind", "ordered", "status",
    "correct", "first_attempt_correct", "failure_reason", "attempts", "model_calls",
    "input_tokens", "output_tokens", "linking_ms", "model_ms", "sql_ms", "total_ms",
    "prompt_version", "backend", "model_id", "dataset_sha256", "questions_sha256",
    "truncated", "row_count", "gold_row_count", "sql", "params", "message",
)
ResultRow = dict[str, str | int | float | None]


class EvaluationError(Exception):
    """The inputs or implementation could not support a complete evaluation."""


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    category: str
    expected_kind: ResponseKind
    ordered: bool
    gold_sql: str | None
    gold_params: dict


def load_questions(path: Path) -> tuple[list[Question], str]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise EvaluationError(f"{path} must use UTF-8 encoding.") from error

    questions = []
    ids = set()
    for line_number, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        location = f"{path}:{line_number}"
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvaluationError(f"Invalid JSON at {location}. {error.msg}.") from error
        if not isinstance(record, dict):
            raise EvaluationError(f"Expected a JSON object at {location}.")

        question_id = record.get("id")
        question_text = record.get("question")
        kind = record.get("expected_kind")
        category = record.get("category", "")
        ordered = record.get("ordered", False)
        if not isinstance(question_id, str) or not question_id.strip():
            raise EvaluationError(f"Missing question id at {location}.")
        if question_id in ids:
            raise EvaluationError(f"Duplicate question id {question_id!r} at {location}.")
        if not isinstance(question_text, str) or not question_text.strip():
            raise EvaluationError(f"Missing question text at {location}.")
        if kind not in ("query", "clarify", "unsupported"):
            raise EvaluationError(f"Invalid expected_kind at {location}.")
        if not isinstance(category, str) or not isinstance(ordered, bool):
            raise EvaluationError(f"Expected a string category and Boolean ordered flag at {location}.")

        gold_sql = None
        gold_params = {}
        if kind == "query":
            gold_sql = record.get("gold_sql")
            gold_params = record.get("gold_params", {})
            if not isinstance(gold_sql, str) or not gold_sql.strip() or not isinstance(gold_params, dict):
                raise EvaluationError(f"Expected gold_sql and a gold_params object for question {question_id!r} at {location}.")
        questions.append(Question(question_id, question_text, category, kind, ordered, gold_sql, gold_params))
        ids.add(question_id)

    if not questions:
        raise EvaluationError(f"No evaluation questions found in {path}.")
    return questions, hashlib.sha256(raw).hexdigest()


def _snapshot_hash(path: Path) -> str:
    with path.open("rb") as database:
        return hashlib.file_digest(database, "sha256").hexdigest()


def _reference_results(questions: list[Question], settings: Settings) -> dict[str, QueryResult]:
    results = {}
    with closing(connect_readonly(settings.db_path)) as db:
        for question in questions:
            if question.gold_sql is None:
                continue
            try:
                gold = run_query(
                    question.gold_sql, question.gold_params, db,
                    timeout_s=settings.sql_timeout_s, max_rows=settings.max_rows,
                )
            except SqlError as error:
                raise EvaluationError(f"Reference SQL failed for {question.id} ({error.kind}). {error.message}") from error
            if gold.truncated:
                raise EvaluationError(
                    f"Reference SQL for {question.id} exceeded the {settings.max_rows}-row cap. Increase --max-rows."
                )
            results[question.id] = gold
    return results


def _failure_reason(question: Question, answer: Answer, gold: QueryResult | None) -> str:
    if question.expected_kind != "query":
        return "" if answer.status == question.expected_kind else "unexpected_status"
    if answer.status not in ("ok", "empty"):
        return "unexpected_status"
    if answer.truncated:
        return "answer_truncated"
    assert gold is not None
    actual_rows = [tuple(row) for row in answer.rows]
    if question.ordered:
        matches = actual_rows == gold.rows
    else:
        matches = Counter(actual_rows) == Counter(gold.rows)
    return "" if matches else "row_mismatch"


def _token_total(answer: Answer, field: str) -> int | None:
    counts = [getattr(call, field) for call in answer.model_calls]
    if answer.attempts > len(counts) or None in counts:
        return None
    return sum(counts)


def evaluate(questions: list[Question], questions_sha256: str, method: str, settings: Settings) -> list[ResultRow]:
    if method not in METHODS:
        raise EvaluationError(f"Unknown method {method!r}.")
    if method == "A":
        from eval.templates import answer as template_answer

        predict = partial(template_answer, settings=settings)
        backend = model_id = prompt_version = ""
    else:
        from rowsetta.pipeline import answer as pipeline_answer
        from rowsetta.prompts import PROMPT_VERSION

        backend = "gemini" if method == "E" else "ollama"
        settings = replace(settings, backend=backend)
        model_id = settings.gemini_model if method == "E" else settings.ollama_model
        prompt_version = PROMPT_VERSION
        predict = partial(pipeline_answer, settings=settings, method=method)

    dataset_sha256 = _snapshot_hash(settings.db_path)
    references = _reference_results(questions, settings)
    rows: list[ResultRow] = []
    for question in questions:
        started = perf_counter()
        try:
            answer = predict(question.text)
        except NotImplementedError as error:
            raise EvaluationError(f"Method {method} is unavailable until {error} is implemented.") from error
        except (SqlError, sqlite3.Error) as error:
            message = error.message if isinstance(error, SqlError) else str(error)
            answer = Answer("error", question.text, message=message)
        elapsed_ms = (perf_counter() - started) * 1000

        gold = references.get(question.id)
        failure = _failure_reason(question, answer, gold)
        correct = not failure
        timings = answer.timings_ms
        model_calls = len(answer.model_calls)
        model_ms = timings.get("model")
        if model_ms is None and answer.attempts <= model_calls:
            model_ms = sum((call.latency_ms for call in answer.model_calls), 0.0)
        actual_models = dict.fromkeys(call.model for call in answer.model_calls)
        rows.append({
            "id": question.id,
            "method": method,
            "category": question.category,
            "question": question.text,
            "expected_kind": question.expected_kind,
            "ordered": int(question.ordered),
            "status": answer.status,
            "correct": int(correct),
            # A second attempt follows a first-attempt SQL failure.
            "first_attempt_correct": int(correct and answer.attempts <= 1),
            "failure_reason": failure,
            "attempts": answer.attempts,
            "model_calls": model_calls,
            "input_tokens": _token_total(answer, "input_tokens"),
            "output_tokens": _token_total(answer, "output_tokens"),
            "linking_ms": timings.get("linking"),
            "model_ms": model_ms,
            "sql_ms": timings.get("sql"),
            "total_ms": timings.get("total", elapsed_ms),
            "prompt_version": prompt_version,
            "backend": backend,
            "model_id": " | ".join(actual_models) or model_id,
            "dataset_sha256": dataset_sha256,
            "questions_sha256": questions_sha256,
            "truncated": int(answer.truncated),
            "row_count": len(answer.rows),
            "gold_row_count": len(gold.rows) if gold is not None else None,
            "sql": answer.sql,
            "params": json.dumps(answer.params, ensure_ascii=False, sort_keys=True),
            "message": answer.message,
        })

    if _snapshot_hash(settings.db_path) != dataset_sha256:
        raise EvaluationError("The SQLite snapshot changed during evaluation. Run again against a stable snapshot.")
    return rows


def write_results(rows: list[ResultRow], method: str, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = directory / f"{method}_{timestamp}.csv"
    with TemporaryDirectory(dir=directory, prefix=".eval-") as staging:
        pending = Path(staging) / output.name
        with pending.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=RESULT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        pending.replace(output)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score Rowsetta answers against a JSONL question set.")
    parser.add_argument("--method", choices=METHODS, required=True)
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    parser.add_argument("--max-rows", type=int, help="row cap for both answers and reference queries")
    args = parser.parse_args(argv)
    if args.max_rows is not None and not 0 < args.max_rows < sys.maxsize:
        parser.error("--max-rows must be a positive row count.")

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    settings = Settings.from_env()
    if args.max_rows is not None:
        settings = replace(settings, max_rows=args.max_rows)
    try:
        questions, checksum = load_questions(args.questions)
        rows = evaluate(questions, checksum, args.method, settings)
        output = write_results(rows, args.method, RESULTS_DIR)
    except (EvaluationError, OSError, sqlite3.Error) as error:
        print(f"Evaluation failed. {error}", file=sys.stderr)
        return 1

    for kind, label in (("query", "Execution accuracy"), ("clarify", "Clarification"), ("unsupported", "Unsupported")):
        matching = [row for row in rows if row["expected_kind"] == kind]
        if matching:
            total_correct = sum(row["correct"] for row in matching)
            print(f"{label} {total_correct}/{len(matching)} ({total_correct / len(matching):.1%})")
    print(f"Wrote {len(rows)} results to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
