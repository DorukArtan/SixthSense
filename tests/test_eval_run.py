import csv
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest

from eval import run
from rowsetta import pipeline, prompts
from rowsetta.settings import Settings
from rowsetta.types import Answer, ModelCall, QueryResult
from tests.test_design import FIXTURES, MAY, build_sample

COUNTRY_QUESTION = "Mayıs 2011'de Fransa ve Almanya'nın net satışını karşılaştır"
GOLD_ROWS = [("France", 325000), ("Germany", 181250)]


@pytest.fixture
def settings(tmp_path):
    path = tmp_path / "rowsetta.sqlite"
    build_sample(path)
    return Settings(db_path=path)


def country_record():
    return {
        "id": "country-comparison",
        "category": "filter_group",
        "question": COUNTRY_QUESTION,
        "expected_kind": "query",
        "ordered": True,
        "gold_sql": (FIXTURES / "country_net.sql").read_text(encoding="utf-8"),
        "gold_params": MAY,
    }


def write_questions(path, *records):
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
    return path


def test_cli_writes_method_a_results(tmp_path, monkeypatch, capsys, settings):
    questions = write_questions(tmp_path / "questions.jsonl", country_record(), {
        "id": "ambiguous",
        "question": "En çok satan ürün hangisi?",
        "expected_kind": "clarify",
    })
    output = tmp_path / "results"
    monkeypatch.setattr(run, "RESULTS_DIR", output)
    monkeypatch.setenv("ROWSETTA_DB", str(settings.db_path))

    assert run.main(["--method", "A", "--questions", str(questions)]) == 0

    result_path, = output.glob("A_*.csv")
    with result_path.open(encoding="utf-8", newline="") as stream:
        correct, ambiguous = list(csv.DictReader(stream))
    assert correct["question"] == COUNTRY_QUESTION
    assert (correct["method"], correct["status"], correct["correct"], correct["first_attempt_correct"]) == (
        "A", "ok", "1", "1",
    )
    assert correct["attempts"] == correct["model_calls"] == correct["input_tokens"] == correct["output_tokens"] == "0"
    assert correct["row_count"] == correct["gold_row_count"] == "2"
    assert correct["dataset_sha256"] == hashlib.sha256(settings.db_path.read_bytes()).hexdigest()
    assert correct["questions_sha256"] == hashlib.sha256(questions.read_bytes()).hexdigest()
    assert json.loads(correct["params"])["c1"] == "France"
    assert (ambiguous["status"], ambiguous["correct"], ambiguous["failure_reason"]) == ("error", "0", "unexpected_status")
    summary = capsys.readouterr().out
    assert "Execution accuracy 1/1 (100.0%)" in summary
    assert "Clarification 0/1 (0.0%)" in summary


@pytest.mark.parametrize(("method", "backend", "attempts"), [
    ("B", "ollama", 1), ("C", "ollama", 1), ("D", "ollama", 2), ("E", "gemini", 2),
])
def test_model_methods_route_and_record_final_and_first_attempt_scores(
    tmp_path, monkeypatch, settings, method, backend, attempts,
):
    def predict(question, settings, *, method):
        calls.append((question, settings.backend, method))
        model_calls = [ModelCall(backend, "actual-model", latency_ms=12.0, input_tokens=10, output_tokens=5)]
        if attempts == 2:
            model_calls.append(ModelCall(backend, "actual-model", latency_ms=8.0, output_tokens=3))
        return Answer(
            "ok", question, rows=GOLD_ROWS, attempts=attempts, model_calls=model_calls, timings_ms={"total": 42.0},
        )

    calls = []
    monkeypatch.setattr(pipeline, "answer", predict)
    monkeypatch.setattr(prompts, "PROMPT_VERSION", "test-version")
    path = write_questions(tmp_path / "questions.jsonl", country_record())
    questions, checksum = run.load_questions(path)
    result, = run.evaluate(questions, checksum, method, replace(settings, backend="other"))

    assert calls == [(COUNTRY_QUESTION, backend, method)]
    assert result["correct"] == 1
    assert result["first_attempt_correct"] == int(attempts == 1)
    assert result["model_calls"] == attempts
    assert result["input_tokens"] == (10 if attempts == 1 else None)
    assert result["output_tokens"] == (5 if attempts == 1 else 8)
    assert result["model_id"] == "actual-model"
    assert result["backend"] == backend
    assert result["prompt_version"] == "test-version"
    assert result["model_ms"] == (12.0 if attempts == 1 else 20.0)
    assert result["total_ms"] == 42.0


@pytest.mark.parametrize(("ordered", "rows", "truncated", "failure"), [
    (False, [(2,), (2,), (1,)], False, ""),
    (True, [(2,), (2,), (1,)], False, "row_mismatch"),
    (False, [(1,), (2,)], False, "row_mismatch"),
    (False, [(1,), (2,), (3,)], False, "row_mismatch"),
    (False, [(1,), (2,), (2,)], True, "answer_truncated"),
])
def test_scoring_respects_order_duplicate_counts_and_truncation(ordered, rows, truncated, failure):
    question = run.Question("test", "Question", "ranking", "query", ordered, "SELECT 1", {})
    gold = QueryResult(["number"], [(1,), (2,), (2,)], False, 0.0)
    answer = Answer("ok", question.text, rows=rows, truncated=truncated)
    assert run._failure_reason(question, answer, gold) == failure


@pytest.mark.parametrize("kind", ["clarify", "unsupported"])
def test_non_query_outcomes_are_scored_by_status(kind):
    question = run.Question("test", "Question", "", kind, False, None, {})
    assert run._failure_reason(question, Answer(kind, question.text), None) == ""
    assert run._failure_reason(question, Answer("error", question.text), None) == "unexpected_status"


def test_truncated_reference_stops_before_model_calls(tmp_path, monkeypatch, settings):
    def predict(*args, **kwargs):
        pytest.fail("The model was called before checking the reference results")

    monkeypatch.setattr(pipeline, "answer", predict)
    questions, checksum = run.load_questions(write_questions(tmp_path / "questions.jsonl", country_record()))
    with pytest.raises(run.EvaluationError, match=r"country-comparison exceeded the 1-row cap"):
        run.evaluate(questions, checksum, "D", replace(settings, max_rows=1))


def test_snapshot_change_invalidates_the_run(tmp_path, monkeypatch, settings):
    def predict(question, settings, *, method):
        with closing(sqlite3.connect(settings.db_path)) as db, db:
            db.execute("UPDATE products SET product_name = 'New label' WHERE stock_code = 'A001'")
        return Answer("ok", question, rows=GOLD_ROWS)

    monkeypatch.setattr(pipeline, "answer", predict)
    questions, checksum = run.load_questions(write_questions(tmp_path / "questions.jsonl", country_record()))
    with pytest.raises(run.EvaluationError, match="snapshot changed"):
        run.evaluate(questions, checksum, "D", settings)


def test_empty_question_file_fails_without_a_results_csv(tmp_path, monkeypatch, capsys):
    path = write_questions(tmp_path / "empty.jsonl")
    output = tmp_path / "results"
    monkeypatch.setattr(run, "RESULTS_DIR", output)

    assert run.main(["--method", "A", "--questions", str(path)]) == 1
    assert "No evaluation questions found" in capsys.readouterr().err
    assert not output.exists()
