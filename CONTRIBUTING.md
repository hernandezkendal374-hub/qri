# Contributing to QRI

Thank you for helping improve QRI. The project values auditable research workflows, small focused changes, and clear boundaries between evidence and speculation.

## Before opening a pull request

- Read the product boundary in `README.md`.
- Do not commit `.env`, API keys, databases, downloaded PDFs, generated logs, or private research data.
- Keep formal `Paper`, `Claim`, and `Evidence` records separate from unverified community observations.
- Add or update tests for behavior changes.

## Local checks

```bash
pip install -e ".[dev]"
pytest -q
ruff check .
mypy app
```

To see your change in the UI without configuring PostgreSQL or a model
endpoint, seed the synthetic dataset:

```bash
alembic upgrade head
qri demo
uvicorn app.main:app --reload
```

Schema changes need an Alembic revision whose additive steps are guarded, since
the 0001 baseline builds the schema from `Base.metadata` and a new database
already has the columns later revisions add. `tests/test_migrations.py` covers
upgrade, schema-vs-model parity, idempotency, and a full downgrade cycle; CI
also runs the chain against PostgreSQL.

## Pull requests

Describe the problem, the change, and the evidence that the change works. Schema changes require an Alembic migration and a note about backward compatibility. UI changes should include the affected route and a short before/after description.

Maintainers may request a smaller change when a proposal mixes ingestion, evidence modeling, and downstream trading logic. QRI is a research-intelligence layer; broker execution belongs in a separate system.
