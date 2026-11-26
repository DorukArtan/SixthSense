"""Smoke checks for the shared contracts in rowsetta/types.py."""

from __future__ import annotations

import json
from pathlib import Path

from rowsetta.types import MODEL_RESPONSE_SCHEMA, ModelResponse, SqlError

ROOT = Path(__file__).resolve().parent.parent


def test_schema_fields_match_model_response():
    fields = set(ModelResponse.__dataclass_fields__)
    assert set(MODEL_RESPONSE_SCHEMA["properties"]) == fields
    assert set(MODEL_RESPONSE_SCHEMA["required"]) == fields


def test_repairable_errors():
    assert SqlError("column", "no such column: x").repairable
    assert not SqlError("policy", "DELETE is not allowed").repairable


def test_glossary_is_valid_json():
    glossary = json.loads((ROOT / "config" / "glossary_tr.json").read_text(encoding="utf-8"))
    assert {"metrics", "countries", "months"} <= set(glossary)
