# Fact Ledger

[![CI](https://github.com/mfdel/fact-ledger/actions/workflows/ci.yml/badge.svg)](https://github.com/mfdel/fact-ledger/actions/workflows/ci.yml)

Fact Ledger reads the documents a company sends to an investor, checks the figures against each other, and writes the questions to ask management before you build a valuation model.

<p align="center"><a href="docs/media/fact_ledger_demo.mp4"><img src="docs/media/fact_ledger_demo.gif" alt="50-second walkthrough: six documents about a synthetic company become a fact table, arithmetic checks, questions for management and source-independence verdicts" width="560"></a></p>

The first product is the **Pre-Valuation Intelligence Layer**. It builds an auditable fact base about a target company from mixed-quality sources. Then it checks that fact base for inconsistencies, gaps and patterns. It is not a valuation or forecasting system.

Every number in the fact base keeps its source document, page, label and origin. When two sources disagree, the tool keeps both values. It never averages them.

## What goes in and what comes out

The example is **Halyard Fleet**, an invented telematics company. All companies, documents and figures in this repository are synthetic.

**Input: six documents about one company**

| Document | What it says |
|---|---|
| Management deck | ARR EUR 19.68m (p4), MRR EUR 1.64m at December 2024 (p7), 43,600 vehicles tracked (p6), 41,000 vehicles licensed (p6) |
| Audited accounts | Net sales EUR 21.48m |
| CEO podcast | *"We finished 2024 at about €22 million of ARR."* |
| Trade press | *"Halyard Fleet reports ARR of EUR 19.7 million for 2024, the company said in a statement."* |
| Forum post | Revenue EUR 30m |

**Output 1: a fact table.** Each row is one figure with its metric, period, value and the place where the document prints it. These are three of the 62 rows (columns shortened).

```
observation_id     metric_id  period_end  value     locator
halyard-02         arr        2024-12-31  19680000  p4 chart
logisticsdaily-01  arr        2024-12-31  19700000  para 1
podcast-01         arr        2024-12-31  22000000  min 14
```

**Output 2: checks.** The tool tests the figures against SaaS arithmetic. For example, ARR must equal MRR × 12, and the MRR bridge must close.

```
identity_id                     period_end  status
arr_from_mrr                    2024-12-31  violated
mrr_bridge                      2024-12-31  violated
net_new_arr_from_arr            2024-12-31  violated
seats_active_le_seats_licensed  2024-12-31  violated
churn_logo_annual_from_monthly  2024-12-31  held
Checks: 3 held, 4 violated, 3 not checked.
```

**Output 3: questions for management.** These are two of the 11 questions the tool wrote for Halyard, word for word.

> The MRR bridge for the quarter 2024-10-01 to 2024-12-31 does not close. Opening MRR EUR 1,560,000 (p7 chart) plus new EUR 120,000 (p12 waterfall), expansion EUR 41,000 (p12 waterfall) and reactivation EUR 0 (p12 waterfall), minus contraction EUR 12,000 (p12 waterfall) and churned EUR 22,000 (p12 waterfall), gives EUR 1,687,000. The stated closing MRR is EUR 1,640,000 (p7 chart). The bridge overstates the closing MRR by EUR 47,000. Which bridge line or which closing value is wrong?

> Seats in use at 2024-12-31 is 43,600 on p6 ("Vehicles tracked"), above Seats contracted 41,000 on p6 ("Licensed vehicles"). The rule seats_active_le_seats_licensed (seats_active <= seats_licensed) does not allow this. Which value is wrong, or do the two use a different scope or definition?

**What the tool understood about the sources**

- The audited accounts confirm the deck revenue. Two independent origins agree, so revenue is *corroborated*.
- The CEO contradicts the deck in public (ARR EUR 22m against EUR 19.68m). Both values come from management, so the class is *inconsistent*, not *contested*.
- The trade-press article repeats the company. It agrees with the deck, but it is the same origin, so ARR is **not** corroborated.
- The forum post is too unreliable to contest the deck. The tool lists it as *unresolvable* and does not call it a contradiction.

## How well it works

The tool is scored on a seeded-error corpus of 27 synthetic investment packs in [evals/](evals/README.md). The packs plant known defects: arithmetic breaks, definition switches, denominator drift, contradictions between origins, a missing expected metric, a basis gap and a projection break. Eight packs plant nothing. Two are clean controls, and six are decoys built to look suspicious.

| Measure | Result |
|---|---|
| Planted defects found | 17 of 17 |
| True corroborations recognised | 3 of 3 |
| Flags with no planted cause | 0 of 20 |

`make eval` runs the corpus and fails when a change scores worse than [evals/baseline.json](evals/baseline.json). It is part of `make check`, together with 403 test functions (629 tests once parametrised).

[CI](.github/workflows/ci.yml) runs the same gates on every push and pull request, plus the slow tests and a dependency audit. A [second workflow](.github/workflows/container.yml) builds the container, smoke-tests it as a non-root user and scans it with Trivy.

**Limitation.** The corpus is synthetic, and the author of the tool wrote it. It measures detection of the defect types the tool was designed around. It does not measure recall on real data rooms.

## Showcase

Read the full results without running anything: **[docs/showcase/b2b_saas/](docs/showcase/b2b_saas/README.md)**.

| Company | What the pack shows | Questions |
|---|---|---|
| Kestrel Ledger | NRR (89%) below GRR (93%), which cannot be true. A plan that almost doubles growth. A press figure 24% above the deck. | 7 |
| Halyard Fleet | The multi-source example above: support, contradiction, echo and noise. | 11 |
| Pinewick Security | The clean control. Decoys that look suspicious, and the tool stays quiet. | 0 |

The showcase folder holds the synthetic input documents, the recorded extraction of each one, the fact packs, and the unedited tool output.

The architecture is in [docs/fact_ledger_architecture_20260920.md](docs/fact_ledger_architecture_20260920.md).

## Quickstart

You need [uv](https://docs.astral.sh/uv/) and `make`.

```sh
make install   # dependencies + git hooks
make check     # every quality gate
make run       # web service at http://127.0.0.1:8000
```

To reproduce the Halyard output, see **Run it yourself** at the end of the [showcase page](docs/showcase/b2b_saas/README.md).

## Stack

Python 3.14, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic (SQLite first), Jinja + HTMX. Quality gates: ruff, mypy (strict), import-linter, pytest with hypothesis, coverage of at least 85%, pip-audit, seeded-error eval.

## License

Apache-2.0. See [LICENSE](LICENSE).
