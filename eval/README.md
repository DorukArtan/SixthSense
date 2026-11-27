# Evaluation

Owners: runner and method A templates — Mehmet Doruk Artan; test set (`questions.jsonl`, `dev_questions.jsonl`) — written by Duygu Özbek, gold SQL checked by Nilsu Kına.

- `dev_questions.jsonl` — about 20 development questions. Prompts and the glossary are tuned only on these.
- `questions.jsonl` — frozen test set (2 December): 60 answerable + 6 ambiguous + 6 unsupported. Never used in prompts.
- `templates.py` — method A (8–10 fixed SQL templates, no LLM).
- `run.py` — runs methods A–E on the test set and writes `eval/results/<method>_<timestamp>.csv`.

One JSON object per line:

```json
{"id": "T017", "category": "ranking", "question": "Mart 2011'de net satışı en yüksek 5 ülke hangisi?", "expected_kind": "query", "gold_sql": "SELECT country, SUM(net_u) AS net_sales_u FROM sales WHERE invoice_at >= :start AND invoice_at < :end GROUP BY country ORDER BY net_sales_u DESC LIMIT 5", "gold_params": {"start": "2011-03-01 00:00:00", "end": "2011-04-01 00:00:00"}, "ordered": true, "author": "...", "checked_by": "..."}
```

- `category`: `filter_group` | `ranking` | `temporal_credit` | `ambiguous` | `unsupported`
- `expected_kind`: `query` | `clarify` | `unsupported`
- `ordered`: compare row order when true, row multisets (with duplicate counts) when false
- Compare money in integer units before display rounding.

Execution accuracy = answerable questions whose result equals the gold result / 60. Errors and unexpected clarifications count as failures.

## Run an evaluation

```bash
python eval/run.py --method A --questions eval/dev_questions.jsonl
python eval/run.py --method D
```

The runner validates the JSONL and executes the reference SQL before scoring answers. Methods B, C and D use the configured local Ollama model. Method E uses Gemini. The CSV records the SHA-256 of the SQLite snapshot and question file so runs using the same inputs can be compared.

`correct` scores the final answer and `first_attempt_correct` counts a repaired query as a first-attempt failure. Clarification and unsupported-question scores use their expected statuses. The CSV includes per-question timings in milliseconds, attempts, model calls, token counts and the SQL or error message. Unreported token counts are blank.

Use the same `--max-rows` for all methods in a comparison. If a reference query exceeds that cap, raise it so the runner can compare complete rows.
