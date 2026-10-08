# Pre-Valuation Intelligence Layer — proposed architecture

**Written:** 2026-09-20 · **Author:** Fuat Deligöz (design)

---

## 1. What this is

A system that builds an **auditable fact base about a target company from mixed-quality
sources**, then interrogates that fact base for inconsistencies, gaps and patterns — producing
the material an analyst needs before forming a view.

**The user is the investor** (analyst, investment manager) on a fund's deal team reviewing a
company's data room. The target company is the *subject*, not the user.

A fund cannot require a target to hand over its Stripe account or a live feed from its ledger.
It works from what the company chose to send — the deck, the banker's pack, the data-room
export — plus interviews, trade press and competitor pages. This system is designed for that
material.

**It is explicitly not a valuation or forecasting system.** It produces the inputs a valuation
consumes: which facts are established, which are contested, which are missing, and what to ask
management.

### Non-goals (state these out loud)

| Not doing | Why |
|---|---|
| Valuation / DCF | Downstream. Different discipline. |
| Forecasting | Downstream. A forecast model consumes this fact base; it is not built here. |
| Ingesting live system feeds (ledger, billing, payments) | A different problem with verified inputs. This system exists precisely for when the only input is what the company sent. |

---

## 2. Core data model

Everything in the system is an **Observation**. One asserted value, about one entity, for one
metric, over one period, from one origin.

### 2.1 Observation

| Field | Purpose |
|---|---|
| `observation_id` | Primary key |
| `entity_id` | Target company **or** a comparable — same schema for both |
| `metric_id` | FK into the metric dictionary (§2.2) |
| `value`, `unit`, `currency` | The number |
| `stated_precision` | "~€8m" → 0.5m. Drives tolerance in §4. Do not skip this field. |
| `period_start`, `period_end`, `period_type` | FY / Q / TTM / point-in-time |
| `as_of_date` | The date the value **describes** |
| `published_date` | The date the statement was **made** |
| `origin_id` | Who originally asserted it (§2.3) |
| `document_id`, `locator` | Where we read it — page, row, URL fragment, transcript timestamp |
| `source_type` | deck / filing / interview / press / web / rumour |
| `reliability` | Score on the origin's general trustworthiness |
| `bias_direction` | up / down / neutral / unknown |
| `stated_label` | The verbatim words used ("recurring revenue run-rate") |
| `definition_status` | resolved / **ambiguous** + candidate `metric_id`s |
| `derivation` | null if observed; else `identity_id` + input `observation_id`s |
| `confidence` | Propagated (§2.4) |

**Design rules that matter:**

- **`as_of_date` and `published_date` are separate fields.** A 2024 interview quoting a 2019
  revenue figure is `published=2024`, `as_of=2019`. Conflating them silently corrupts every
  timeseries. Old data is *not* degraded data — the long history is exactly what a deck
  showing two years is hiding.
- **`definition_status = ambiguous` is a valid, desirable end state.** "Revenue" in a SaaS deck
  may mean ARR, recognised revenue or billings. **Do not build an extractor that resolves the
  ambiguity — build one that records it.** The ambiguity is a finding, and it feeds §4. The
  validator may read an ambiguous value as the one candidate metric it matches. That reading is
  an assumption: it is calculated again on each run, shown as `inferred`, and never stored.
- **Derived observations are first-class**, carrying their identity and inputs. The fact base
  never loses the distinction between what was asserted and what was computed.

### 2.2 Metric dictionary — build this instead of tagging datapoints

Tagging each datapoint with "related KPIs" says two things are related without saying *how*,
and the labeling cost grows with the data. Define the **relationships** once instead:

```
revenue      = customers × ARPU
ARR          = MRR × 12
LTV          = ARPU × gross_margin / churn_rate
growth_yoy   = revenue[t] / revenue[t-1] − 1
CAC_payback  = CAC / (ARPU × gross_margin)
burn_multiple= net_burn / net_new_ARR
NRR          = (start_ARR + expansion − contraction − churn) / start_ARR
```

**Dictionary entry:**

| Field | Purpose |
|---|---|
| `metric_id`, `canonical_name` | The node |
| `aliases[]` | "ARR", "annual recurring revenue", "run-rate revenue" → one node. **This is where the real extraction work lives.** |
| `dimension` | currency / count / ratio / percent / months |
| `stock_or_flow` | Point-in-time vs period-accumulated. Governs valid period arithmetic. |
| `definition_note` | The precise definition this system means |
| `expected_for[]` | (sector, stage) pairs where this metric *should* be disclosed. Drives the absence test in §5. |

**Identity entry:**

| Field | Purpose |
|---|---|
| `identity_id`, `equation` | The relation |
| `terms[]` | Metric ids |
| `validity_conditions` | Same entity, aligned periods, same currency, compatible stock/flow |
| `tolerance_policy` | Per §4 |

**One structure, two behaviours — this is the point:**

- An identity with **exactly one unknown** → a **derivation**. (Agent 1)
- An identity where **every term is independently observed** → a **check**. (Agent 2)

You label a vocabulary of ~30–40 metrics once, not every datapoint, and both agents fall out.

### 2.3 Origin vs document — the echo problem

`origin_id` is **who originally asserted the number**. `document_id` is where we found it.

Three trade-press articles recycling one company press release are **one origin, three
documents**. Counting them as three corroborations inflates confidence exactly where the
information is weakest — and for private-company figures scraped from the web, echo is the
dominant mode, not the exception.

**Corroboration = count of distinct origins, never count of documents.**

And the payoff is not only confidence: **disagreement between independent origins is a
finding.** Deck says 40% growth, an independent origin implies 25% — that goes straight to
Agent 2 as a contested fact, not to a mean.

### 2.4 Confidence propagation

Three separate scores; do not collapse them into one number.

1. **Reliability** — the origin's general trustworthiness. Deck 4/5, interview 2/5, rumour 1/5.
2. **Corroboration** — distinct independent origins asserting a compatible value.
3. **Bias direction** — a banker's pack is not merely "4/5", it is *systematically skewed up*.
   A departing employee's account skews down. **Direction of error is more actionable than
   magnitude**, and it is the field an investor reads first.

**Propagation rule for derived values: weakest link.** Revenue-per-customer computed from a
4/5 revenue and a 2/5 customer count is **2/5**, not 3/5. State this explicitly; it is a small
rule that determines whether the fact base can be trusted at all.

---

## 3. Components to build

```
   ┌─────────────┐  ┌─────────────┐  ┌──────────────┐
   │ Deck        │  │ Web         │  │ Comparables  │
   │ extractor   │  │ extractor   │  │ collector    │
   └──────┬──────┘  └──────┬──────┘  └──────┬───────┘
          └────────────────┼────────────────┘
                           ▼
                  ┌──────────────────┐
                  │ Origin resolver  │  dedupe echoes → distinct origins
                  └────────┬─────────┘
                           ▼
        ┌──────────────────────────────────────┐
        │  FACT STORE (Observations)           │◄─── Metric dictionary
        └───┬──────────────┬──────────────┬────┘     + identities
            ▼              ▼              ▼
     ┌────────────┐ ┌────────────┐ ┌─────────────┐
     │ A1 Derive  │ │ A2 Validate│ │ A3 Patterns │
     └─────┬──────┘ └─────┬──────┘ └──────┬──────┘
           └──────────────┼───────────────┘
                          ▼
                 ┌──────────────────┐
                 │ ANALYST BRIEF    │
                 └──────────────────┘
```

| # | Component | Purpose | Build priority |
|---|---|---|---|
| C1 | **Metric dictionary + identities** | The vocabulary. Nothing works without it. | **1st** |
| C2 | **Fact store** | Observation schema + query by (entity, metric, period) | **1st** |
| C3 | **Deck extractor** | PDF/PPT → observations, with locator and stated_label preserved | 2nd |
| C4 | **Origin resolver** | Collapse echoed documents to origins | 4th |
| C5 | **Web extractor** | Interviews, filings, press, company pages → observations | 4th |
| C6 | **A1 Derivation** | Fill identities with one unknown. **Plumbing, not the idea** — any mature financial data model already does this. Do not present it as the innovation. | 3rd |
| C7 | **A2 Validator** | Multi-path computation and divergence classification (§4) | **2nd — the core** |
| C8 | **A3 Pattern & narrative** | Red-flag library, story hypotheses, falsifying questions (§5) | 5th |
| C9 | **Comparables collector** | Same pipeline, `entity_id` = competitor. Designed as the slot where a benchmark source plugs in. | 6th |
| C10| **Analyst brief renderer** | The consumable output (§6) | 3rd |
| C11| **Seeded-error eval** | The correctness measurement (§7) | With C7 |

---

## 4. Agent 2 — the validator (the distinctive component)

**Purpose:** find where the company's own numbers disagree, and turn each disagreement into a
question for management.

**Procedure**, per `(entity, metric, period)`:

1. Enumerate every computation path — direct observations plus every identity that resolves.
2. Compute all paths. Keep each path's inputs and confidence.
3. Compare pairwise and classify the divergence.

**Divergence classification — the output is a class, not a number:**

| Class | Condition | Output |
|---|---|---|
| **Corroborated** | Within tolerance, ≥2 **independent origins** | Confidence up; no finding |
| **Consistent** | Within tolerance, same origin | No finding (it is arithmetic, not evidence) |
| **Inconsistent** | Outside tolerance, same origin, same `stated_label` | **Finding**: "ARR €8.06m on p.4, €7.45m on p.14, same label" → question to management |
| **Definitional** | Outside tolerance, and `stated_label` differs between paths | **Finding**: "ARR on p.4, recognised revenue on p.11, growth computed across both" |
| **Contested** | Outside tolerance, independent origins, no definitional cause | **Finding** → question to management |
| **Unresolvable** | Outside tolerance, inputs too weak to adjudicate | Flag as open; do not average |

**Never average two conflicting values into one.** The disagreement is the product.

**Tolerance model — this is what stops a wall of false positives:**

- Start from `stated_precision`. "~€8m" against a computed €8.3m is **not** an inconsistency.
- Relative tolerance by metric class — ratios tighter than absolute currency amounts.
- Period-alignment check before comparison: fiscal vs calendar, TTM vs FY.
- Currency normalisation using an FX rate stamped at `as_of_date`, not today.

A naive `a == b` comparison produces noise and destroys trust in the tool on first use.
**Encoding what counts as a real inconsistency versus a definitional difference is where
domain experience is decisive, and it is the part a generic AI engineer cannot specify.**

---

## 5. Agent 3 — patterns, stories, questions

**Not statistical outlier detection.** An investment pack yields a handful of ragged annual
points; there is no density for anomaly detection, and "what is the story?" is the highest
hallucination risk in the system.

### 5.1 Red-flag library — deterministic checks over the fact base

| # | Check | Computable as |
|---|---|---|
| 1 | **Definition switch mid-document** | `stated_label` changes across periods of one metric, one document |
| 2 | **Coverage asymmetry** | Density of the metric × year matrix; recent years richly covered, earlier years thin |
| 3 | **Conspicuous absence** | Set difference: `expected_for(sector, stage)` minus metrics present. *A deck that goes deep on metrics with no NRR is telling you something.* |
| 4 | **Inflection at the raise** | Trend break located at a financing event boundary |
| 5 | **Projection discontinuity** | Projected CAGR materially exceeds realised CAGR with no stated cause |
| 6 | **Selective cohort disclosure** | Cohort data present for a subset of cohorts only |
| 7 | **Denominator drift** | "Customers" changes meaning (logos → seats → accounts) across periods |
| 8 | **Unexplained growth composition** | Growth not decomposed into price / volume / acquisition |
| 9 | **Cross-origin contradiction** | Inherited from Agent 2's *Contested* class |

Check 3 replaces "a metric reported last year is missing this year" — that version assumed a
stable reporting cadence this system does not have. **"What is conspicuously missing given
everything else they chose to show"** needs only one document plus a domain checklist.

### 5.2 Story synthesis — with a hard rule

A **story** is a hypothesis linking findings: *"Growth decelerated through 2023 while headcount
grew 40% — they hired ahead of a demand curve that did not arrive."*

> **Rule: every story must decompose into the questions that would confirm or kill it.**
> A story that cannot name its own test is dropped.

This is the hallucination control, and it needs no judge model. It also produces the
deliverable the analyst actually uses — the **management question list**.

---

## 6. Output — the analyst brief

The consumable artifact. Not a memo; an interrogation pack.

1. **Fact table** — every metric × period, with value, confidence, bias direction, origin count,
   and a locator per claim. Contested cells show *both* values, never a blend.
2. **Inconsistencies** — Agent 2 findings, each showing the two computation paths side by side.
3. **Conspicuous absences** — expected and not disclosed.
4. **Patterns** — red-flag hits with their evidence.
5. **Stories** — hypotheses, each with its falsifying questions attached.
6. **Management question list** — the deduplicated, prioritised output of 2, 3 and 5.
   **This is what the analyst carries into the next meeting.**

---

## 7. How correctness is measured

Not an LLM judging prose. **A seeded-error corpus.**

Take a realistic investment pack. Inject a known set of defects: a definitional switch, an
arithmetic inconsistency, a removed expected metric, a denominator drift, a projection break.
Run the system. Measure:

| Metric | Definition |
|---|---|
| **Detection rate** | Seeded defects found / seeded defects planted |
| **False-positive rate** | Flags raised that correspond to no seeded defect |
| **Localisation** | Did the flag cite the correct source rows? |
| **Question quality** | Does the generated question name the actual discrepancy? |

Detection and false-positive rates are **deterministic and reproducible** — the ground truth is
known because it was planted. This replaces an opinion about quality with a number.

**False-positive rate is the metric that matters most.** An analyst abandons a tool that cries
wolf faster than one that misses things.

---

## 8. Build order

| Stage | Contents | Proves |
|---|---|---|
| **S1** | C1 dictionary + C2 fact store, hand-populated from one real deck | The data model holds real, messy data |
| **S2** | C7 validator + C11 seeded-error eval | **The core claim, with a number attached** |
| **S3** | C3 deck extractor + C10 brief renderer | End-to-end on one document |
| **S4** | C6 derivation + C8 pattern library | Coverage |
| **S5** | C4 origin resolver + C5 web extractor | Multi-origin confidence becomes real |
| **S6** | C9 comparables | Sector context |

**For a first demonstration, build S1 + S2 only.** Two contradictory numbers from one deck, each
traced to its page, is a finding an investor feels instantly and that needs no explanation.
