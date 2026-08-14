# QRI — Quant Research Intelligence

QRI is an auditable research-intelligence system for quantitative finance. It turns a large stream of papers into a small number of research briefs that a human can review, rather than generating a trading strategy for every paper.

## What QRI does

QRI answers three questions:

1. What is worth researching?
2. Why is it worth researching?
3. How could the claim be falsified?

The pipeline is deliberately incremental:

```text
Research sources
  -> radar scan (title, abstract, metadata)
  -> scout review (incremental value and conflicts)
  -> deep research for a small, thresholded set
  -> Research Brief and Validation Spec
  -> one human decision: approve, defer, or reject
```

The system can return “no high-value new question today”. It does not fill a quota with low-value output.

## Product boundary

QRI preserves the paper, claim, and evidence chain. It can describe variables, samples, controls, falsification tests, and data requirements. It does not choose portfolio weights, execution rules, broker connections, or live trades. Statistical tests are research tools, not investment advice.

Community material is kept in a separate shadow layer. It may suggest an attack point or a reproduction task, but it cannot promote an unverified post into formal evidence.

## Local quickstart

Requirements: Python 3.12+ and a local PostgreSQL database (SQLite is useful for development fixtures).

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Useful pages:

- `/dashboard` — daily radar and the single human decision gate
- `/papers` — paper library and full-text status
- `/claims` — author claims and evidence pointers
- `/questions` — Research Briefs and Validation Specs
- `/daily-best` — daily research archive
- `/themes` — long-lived themes and knowledge deltas
- `/community-attack-radar` — unverified community attack points

The CLI mirrors the funnel. For example:

```powershell
qri daily --target 300
qri daily-funnel
```

## Configuration

Copy `.env.example` to `.env`. Keep keys and personal emails in `.env`; it is intentionally ignored by Git. `DAILY_SCAN_TARGET`, `SCOUT_MAX_ITEMS`, `DEEP_RESEARCH_MAX_ITEMS`, and their thresholds are safety limits, not quotas that must be filled.

## Development

```powershell
pytest -q
ruff check .
mypy app
```

Pull requests should include tests for behavior changes and should not add papers, PDFs, databases, API keys, or generated logs to the repository.

## Status and license

QRI is an early-stage open-source project. Interfaces and schemas may evolve while the evidence chain remains backward-compatible. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and [LICENSE](LICENSE) for the MIT License.
