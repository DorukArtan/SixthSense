"""Step 3 - Prompt construction.

Owner: Muhammed Said Tosun

The prompt holds: the schema summary (db/schema.sql), metric definitions,
the values linking.py matched, and 3-5 examples from eval/dev_questions.jsonl.
Never put a test question (eval/questions.jsonl) into a prompt.

Keep a PROMPT_VERSION string and bump it on every change; eval/run.py records it.
"""

from __future__ import annotations

from rowsetta.types import LinkedQuestion

PROMPT_VERSION = "0.0"


def build_messages(linked: LinkedQuestion, *, use_glossary: bool = True) -> list[dict]:
    """Chat messages for the first attempt.

    use_glossary=False gives method B (question + schema only, no linking hints).
    """
    raise NotImplementedError("prompts.build_messages")


def build_repair_messages(
    linked: LinkedQuestion, failed_sql: str, error_message: str
) -> list[dict]:
    """Chat messages for the single repair attempt after a repairable SqlError."""
    raise NotImplementedError("prompts.build_repair_messages")
