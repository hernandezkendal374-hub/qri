# QRI — Quant Research Intelligence

**Turn a firehose of quantitative-finance papers into a handful of falsifiable research questions, each carrying the verbatim evidence behind it.**

[简体中文](README.zh-CN.md) · [Contributing](CONTRIBUTING.md) · MIT licensed

QRI scans roughly 300 papers a day and compresses them into a small number of
Research Briefs worth a human decision. It answers three questions — what is
worth researching, why, and what result would prove it wrong — and it stops
there. It does not generate trading strategies, size positions, or dress a
statistical test up as investment advice.

![Today's research radar](docs/screenshots/dashboard.png)

*The daily radar: 8 papers scanned in this demo dataset, 3 reaching Scout, 2
reaching deep research, and one Research Brief waiting on a human decision.*

## See it in 60 seconds

No PostgreSQL, no API key, no network access. The demo dataset is synthetic —
the papers, authors and numbers are invented — but it exercises the same code
paths as a real run.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
alembic upgrade head
qri demo
uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000/dashboard>.

> The web UI binds to localhost and has **no authentication**. Several
> endpoints spend money on model calls and start background processes, so do
> not expose the port to an untrusted network.

## What makes it different

Most literature tools summarise. QRI is built around four constraints that are
enforced in code, not just stated in a README:

**Evidence beats summary.** A field on a Research Card is `UNVERIFIED` unless a
quote supporting it occurs *verbatim* in the parsed full text. The locator
resolves each quote to a page and character offset and cross-checks the page
and document offsets against each other; a quote it cannot anchor raises rather
than being stored. See [`app/evidence/locator.py`](app/evidence/locator.py).

**Questions beat conclusions.** An author's claim is recorded as an
`AUTHOR_CLAIM`, never as a system fact. Every extraction prompt says so.

**Falsification first.** A Research Brief is incomplete until it states what
result would overturn the hypothesis, which biases threaten it, and what the
minimum data requirement is.

**A statistical test is not a strategy.** Regressions, portfolio sorts, placebo
and out-of-sample tests are research instruments. Nothing reaches a downstream
system without a human approving it — `export_candidate_question()` refuses any
question that is not `HUMAN_APPROVED`.

![A complete Research Brief](docs/screenshots/research-brief.png)

## How the funnel works

```text
~300 papers scanned per day
  → Radar    title + abstract + metadata, keyword heuristics, no AI calls
  → Scout    above the incremental-value threshold, capped, summary-level reading
  → Deep     above the deep-research threshold, capped, may legitimately be 0
  → Research Brief: question, counter-evidence, and a validation spec
  → One human gate: approve / defer / reject
```

Thresholds with caps, not quotas. When nothing clears the bar the dashboard
says so instead of manufacturing a daily digest.

**Radar** is a deliberately cheap first pass: keyword and Jaccard-similarity
heuristics over title and abstract, no model calls. The scores order candidates;
they are not confidence estimates. `LOW_INCREMENTAL_VALUE` and
`NO_MATERIAL_CHANGE` are archived without fetching full text.

**Scout** reads only what cleared the threshold and answers "what does this
change about what we already knew".

**Deep research** fetches legally available full text for the few papers that
clear the deep threshold, then produces the Research Card, claims, evidence
pointers, candidate questions and validation spec.

## Themes, not papers

The unit of work is `ResearchTheme → Evidence Stream → Research Question`, so
the system tracks what changed rather than re-reading the momentum literature
every morning. Each paper lands in a theme and is marked `NO_MATERIAL_CHANGE`,
`LOW_INCREMENTAL_VALUE`, `NEW_CONDITION`, `NEW_EVIDENCE` or `NEW_CONFLICT`, and
every run leaves a `KnowledgeDelta` behind.

![Research themes](docs/screenshots/themes.png)

## Community attack radar (shadow mode)

A separate provider reads the Quantitative Finance StackExchange API for weak
signals that a published result does not survive contact with implementation.
Forum text is treated as `UNTRUSTED_EXTERNAL_CONTENT` throughout: it is never
executed, never followed to external links, never admitted into claims or
evidence, and never allowed to change the daily ranking. It can only produce
`CommunityObservation` rows (`UNVERIFIED` by default) and propose a
`FalsificationTask` for a human to review.

![Community attack radar](docs/screenshots/community-attack-radar.png)

## Paper sources

Discovery aggregates arXiv, OpenAlex, Crossref and Semantic Scholar, with
Unpaywall for legal open-access full text. One source failing does not block
the others. Abstract-only records are marked `ABSTRACT_ONLY` rather than
claiming the full text was read.

## Running it for real

Requires Python 3.12+. Copy `.env.example` to `.env` and set a database URL and
an OpenAI-compatible model endpoint.

```bash
docker compose up -d postgres      # or point DATABASE_URL at your own
alembic upgrade head
uvicorn app.main:app --reload
```

### Pages

| Path | What it shows |
| --- | --- |
| `/dashboard` | Today's radar, funnel progress, and the export decision |
| `/papers` | The paper library |
| `/claims` | Author claims beside their verbatim evidence |
| `/questions` | Full Research Briefs |
| `/daily-best` | The Research Brief archive |
| `/themes` | Long-lived themes and knowledge deltas |
| `/community-attack-radar` | Community weak signals (shadow mode) |

### CLI

```bash
qri demo                                 # synthetic dataset, no network needed
qri daily --target 300
qri radar --scout-max 30 --threshold 0.48
qri briefs --top 30
qri prioritize --deep 5 --threshold 0.62
qri fetch --top 3
qri analyze --top 3
qri claims --top 3
qri questions
qri validation-briefs --top 3
qri community-shadow --query "momentum transaction cost replication"
```

`qri daily-funnel` runs the stages in order and resumes from a failed stage.

### Configuration

```env
PRIMARY_MODEL=claude-sonnet-5       # scouting and paper analysis
REASONING_MODEL=claude-sonnet-5     # question generation
VALIDATION_MODEL=claude-sonnet-5    # research validation specs
```

Any model id your OpenAI-compatible gateway exposes will work. Radar makes no
model calls at all.

Funnel controls are thresholds and safety caps, never quotas to fill:

```env
SCOUT_SCORE_THRESHOLD=0.48
SCOUT_MAX_ITEMS=30
DEEP_RESEARCH_THRESHOLD=0.62
DEEP_RESEARCH_MAX_ITEMS=5
DAILY_SCAN_TARGET=300
COMMUNITY_SHADOW_ENABLED=true
```

Model calls are recorded in an `ai_calls` audit table. QRI ships no vendor
price table, so set your own rates to get costs alongside them:

```env
INPUT_COST_PER_MILLION_TOKENS=0
OUTPUT_COST_PER_MILLION_TOKENS=0
```

## Development

```bash
pytest -q        # tests
ruff check .     # lint
mypy app         # types
```

CI additionally runs the migration chain (upgrade, schema-vs-model check,
idempotent re-upgrade, downgrade to base, upgrade again), the full suite
against PostgreSQL, and the demo path a new user follows.

Layout:

```text
app/web/         HTTP routes, one module per area of the UI
app/radar/       incremental-value triage
app/evidence/    verbatim quote anchoring
app/question_factory/  candidate questions and the export gate
app/providers/   paper sources, community sources, model gateway
app/demo/        the synthetic dataset behind `qri demo`
```

The UI is currently Chinese-only; the code, tests and configuration are in
English. Translating the templates is a good first contribution.

## Scope and limits

QRI is an early but working release. Its output is auditable research leads and
validation plans — **not investment advice, trading signals, or any expectation
of return**. It does not connect to a broker, does not place orders, and does
not turn a statistical test into a tradable strategy. Anything entering a
downstream system passes a human review first.

Legacy strategy incubation and quick backtesting from earlier versions are kept
as a read-only archive at `/legacy-strategies`. Every write path is retired and
returns 410; those records take no part in the radar, ranking, review or export.

Contributions, issues and security reports: [CONTRIBUTING.md](CONTRIBUTING.md),
[SECURITY.md](SECURITY.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
