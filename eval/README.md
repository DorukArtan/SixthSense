# Evaluation

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
