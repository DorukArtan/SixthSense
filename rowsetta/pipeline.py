"""Controller - runs steps 2-7 and owns the single repair attempt.

Owner: Muhammed Said Tosun

Flow (docs/architecture.md, "Sorgu akışı"):
  link -> (ambiguity? return clarify) -> prompt -> model
  -> kind clarify/unsupported? return it
  -> validate -> run -> present
  On a repairable SqlError at validate or run: one repair call, same checks.
  A second failure, a policy rejection, a timeout or a model outage -> status "error".

`method` selects the evaluated configuration:
  "B" direct LLM, "C" LLM + glossary, "D" C + repair (local), "E" D on Gemini.
Method A (templates) lives in eval/templates.py and does not use this function.
"""

from __future__ import annotations

from rowsetta.settings import Settings
from rowsetta.types import Answer


def answer(question: str, settings: Settings, *, method: str = "D") -> Answer:
    raise NotImplementedError("pipeline.answer")
