"""Method A - keyword-matched SQL templates, no LLM (baseline for R5).

Owner: Mehmet Doruk Artan
Cover 8-10 common question shapes (total by country and period, top-N products,
monthly trend ...). Questions outside the templates return status "error".
Uses the same sql.run_query executor as the LLM methods.
"""

from __future__ import annotations

from rowsetta.settings import Settings
from rowsetta.types import Answer


def answer(question: str, settings: Settings) -> Answer:
    raise NotImplementedError("eval.templates.answer")
