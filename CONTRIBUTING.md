# Contributing to QRI

Thank you for helping improve QRI. The project values auditable research workflows, small focused changes, and clear boundaries between evidence and speculation.

## Before opening a pull request

- Read the product boundary in `README.md`.
- Do not commit `.env`, API keys, databases, downloaded PDFs, generated logs, or private research data.
- Keep formal `Paper`, `Claim`, and `Evidence` records separate from unverified community observations.
- Add or update tests for behavior changes.

## Local checks

```powershell
pip install -e ".[dev]"
pytest -q
ruff check .
mypy app
```

## Pull requests

Describe the problem, the change, and the evidence that the change works. Schema changes require an Alembic migration and a note about backward compatibility. UI changes should include the affected route and a short before/after description.

Maintainers may request a smaller change when a proposal mixes ingestion, evidence modeling, and downstream trading logic. QRI is a research-intelligence layer; broker execution belongs in a separate system.
