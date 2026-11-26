# AI Usage Log (R10)

Every use of an AI tool goes here, one row per use. The report's heading 9 table and the AI Usage slide are built from this file. Fill in the "Team member(s)" and "How the output was checked" columns honestly; a row without a check is not finished.

| Date | Tool | What it was used for | Part of the project | Team member(s) | How the output was checked |
| --- | --- | --- | --- | --- | --- |
| 2026-11-20 | Claude | Ranked the 10 course topics by feasibility | Topic selection | Said | TBD |
| 2026-11-26 | ChatGPT | First architecture draft, SQLite schema, synthetic fixture and verification script (`docs/archive/gpt-architecture-draft.md`, `db/schema.sql`, `tests/fixtures/`) | Architecture, data model | TBD | Reviewed by Claude; verification script re-run by: TBD |
| 2026-11-26 | Claude | Review of the GPT draft; architecture and roadmap (`docs/architecture.md`) | Architecture, plan | Said | TBD |
| 2026-11-26 | Claude | Repository skeleton: contracts (`rowsetta/types.py`), module stubs, tests, README, setup script | Code structure | Said | `python -m pytest -q` (12 passed); reviewed by: TBD |
| 2026-11-27 | Codex | Implemented the UCI workbook import, classified non-merchandise codes and built the SQLite snapshot | Data import | Doruk | 14 tests passed. Reconciled row counts and independently reproduced May 2011 France and Germany totals from the UCI workbook. |
| 2026-11-27 | Codex | Implemented SELECT validation, exact named-parameter checks, read-only SQLite execution and query limits | SQL layer | Doruk | 28 tests passed on SQLGlot 25.0.0 and 30.35.0. The May 2011 France and Germany query matched the verified UCI workbook totals. |
| 2026-11-27 | Codex | Implemented nine deterministic SQL templates with Turkish keyword matching for method A | Evaluation baseline | Doruk | 45 tests passed on SQLGlot 25.0.0 and 30.35.0. The May 2011 France and Germany question matched the reference SQL on the UCI snapshot with zero model calls. |

Rules from the course brief: every member must be able to explain any AI-produced part; every reference must be opened and verified; every number must come from our own runs.
