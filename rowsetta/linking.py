"""Step 2 - Turkish term and value linking (schema linking).

Owner: TBD

Maps a Turkish question onto the schema with config/glossary_tr.json:
metric synonyms, Turkish country names -> stored values (Fransa -> France,
Irlanda -> EIRE), Turkish month names and suffixes ("Mayıs'ta") -> half-open
date ranges on the dataset timeline (Dec 2010 - Dec 2011; every month except
December exists only in 2011, so only December needs a year).

If the metric is ambiguous ("en çok satan" = quantity or amount?), add
"metric" to `ambiguities`; the pipeline then asks the user before calling the model.
"""

from __future__ import annotations

import json
from pathlib import Path

from rowsetta.types import LinkedQuestion


def load_glossary(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def link(question: str, glossary: dict) -> LinkedQuestion:
    """Return the metric, countries, period and ambiguities found in `question`."""
    raise NotImplementedError("linking.link")
