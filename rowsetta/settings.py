"""Runtime settings read from the environment (.env is loaded by app.py)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    db_path: Path = ROOT / "data" / "rowsetta.sqlite"
    glossary_path: Path = ROOT / "config" / "glossary_tr.json"
    backend: str = "ollama"  # "ollama" (method D) or "gemini" (method E)
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5-coder:7b-instruct-q4_K_M"  # replaced after the 27 Nov pilot
    gemini_model: str = "gemini-flash-latest"  # copy the exact model id from AI Studio
    gemini_api_key: str | None = None
    sql_timeout_s: float = 3.0
    max_rows: int = 200
    model_timeout_s: float = 60.0

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            db_path=Path(os.getenv("ROWSETTA_DB", defaults.db_path)),
            backend=os.getenv("ROWSETTA_BACKEND", defaults.backend),
            ollama_host=os.getenv("OLLAMA_HOST", defaults.ollama_host),
            ollama_model=os.getenv("OLLAMA_MODEL", defaults.ollama_model),
            gemini_model=os.getenv("GEMINI_MODEL", defaults.gemini_model),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        )
