# SixthSense · Rowsetta

**Rowsetta** answers sales questions written in Turkish. It maps the question to the database fields, has an LLM draft a SQL query, validates and runs it on a read-only SQLite snapshot, and shows the question, the executed SQL, the result table and a chart.

SWE015 Introduction to Large Language Models · Final project · Topic 6 (Text-to-SQL) · Team SixthSense

> Status: architecture and module skeleton. Modules raise `NotImplementedError` until their owners implement them. See [`docs/architecture.md`](docs/architecture.md) for the design, roadmap and owners.

## Setup and run

Requirements: Python 3.11+, [Ollama](https://ollama.com) (for the local model), macOS or Linux.

```bash
cp .env.example .env        # set GEMINI_API_KEY only if you run method E
./scripts/setup.sh && streamlit run app.py
```

`setup.sh` installs the Python packages, downloads the [UCI Online Retail](https://archive.ics.uci.edu/dataset/352/online+retail) workbook, builds `data/rowsetta.sqlite` and pulls the local model. Data files and model weights are not stored in this repository.

## Tests

```bash
python -m pytest -q
```

## Repository layout

| Path | Purpose |
| --- | --- |
| `app.py` | Streamlit interface |
| `rowsetta/types.py` | Shared contracts between modules |
| `rowsetta/linking.py` · `prompts.py` · `model.py` · `sql.py` · `pipeline.py` · `present.py` | Pipeline steps 2–7 |
| `config/glossary_tr.json` | Turkish metric, country and month vocabulary |
| `db/schema.sql` | SQLite schema (money in integer units, 1 GBP = 10,000) |
| `scripts/import_uci.py` | Builds the snapshot from the UCI workbook |
| `eval/` | Test set, method A templates, evaluation runner |
| `tests/` | Data-design checks on a synthetic fixture |
| `docs/` | Architecture, roadmap, AI usage log |

## Data

Chen, D. (2015). *Online Retail* [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5BW33 (CC BY 4.0).

## AI usage

AI tools were used in this project and every use is logged in [`docs/ai-usage.md`](docs/ai-usage.md).
