# Showcase: three B2B SaaS packs

**All companies, documents and figures on this page are synthetic.** They are invented to show what the tool does. No real company data is used.

Three invented B2B SaaS companies each send an investor pack. The tool reads each pack, checks the figures against each other and against SaaS arithmetic, and writes a brief. The brief is a list of the questions to ask management before you build a valuation model.

| Company | Profile | Documents in the pack | Questions raised |
|---|---|---|---|
| [Kestrel Ledger](#kestrel-ledger) | Mid-market finance-operations software, ARR EUR 12.1m | Deck, trade-press article, audited accounts | 7 |
| [Halyard Fleet](#halyard-fleet) | Fleet telematics, software plus devices, ARR EUR 19.7m | Deck, audited accounts, CEO podcast, two press articles, forum post | 11 |
| [Pinewick Security](#pinewick-security) | Enterprise security software, ARR EUR 45.0m | Deck, press article, audited accounts | 0 |

Every finding below comes from the unedited output in [`out/`](out/). The input packs are in [`packs/`](packs/). [`sources/`](sources/) holds the synthetic PDFs and articles, and [`transcripts/`](transcripts/) holds the recorded extraction of each one for the `extract` command. Each pack file says, in its comments, which issues were planted and which rows are decoys.

## What the tool checks in a SaaS pack

- **SaaS arithmetic.** ARR = MRR × 12. The MRR bridge must close. Net revenue retention (NRR) cannot be below gross revenue retention (GRR). Active seats cannot exceed licensed seats. Annual churn must be the compounded monthly churn. For a fast-growing business, ARR must be at least the revenue of the last 12 months.
- **Definitions.** If a deck prints "Revenue" or "Recurring revenue" with no definition, the tool compares the value with each metric it can mean. If no metric matches, it asks which one is meant.
- **Sources.** The tool counts *independent origins*, not documents. When an auditor confirms the deck, the figure is corroborated. When the press repeats the company, it is an echo, and the figure is not corroborated. A conflict between two origins is *contested*. A conflict inside one origin, for example a CEO interview against the deck, is *inconsistent*. A reliability-1 source, such as a forum post, cannot contest anything. See [Halyard Fleet](#halyard-fleet) for all of these in one pack.
- **Plans against history.** If a plan grows ARR more than 10 points a year faster than the realised growth, the tool asks why.
- **Disclosure gaps.** The dictionary lists 53 metrics that a SaaS investor expects. The tool lists each one that the pack does not give and cannot be calculated from the pack.

---

## Kestrel Ledger

A mid-market company growing 47% a year. The pack contains 61 figures.

**Findings**

| # | What the tool found | Why it matters to an investor |
|---|---|---|
| 1 | NRR is 89% and GRR is 93% (p11). NRR cannot be below GRR. | 89% is exactly 1 − 11% annual logo churn. The "NRR" is probably logo retention under an NRR label. Real NRR is unknown, and NRR drives most SaaS valuation multiples. |
| 2 | The FY2025 plan (p15) puts ARR at EUR 22.5m: growth of **86.6%** a year, against **47.1%** realised in 2024. | The plan almost doubles the growth rate. Ask what pipeline, pricing or product change supports it before you use the plan in a model. |
| 3 | A trade-press article states ARR of EUR 15.0m. The deck shows EUR 12.06m (p4), and MRR × 12 also gives EUR 12.06m. | The labels differ ("annual recurring revenue" in the press, "ARR (exit)" in the deck), so the tool asks whether the two use the same definition. Somebody gave the press a number 24% above the deck. |
| 4 | Follow-on from 3: the press ARR implies net new ARR of EUR 6.8m. The deck shows EUR 3.86m. | The tool cannot judge this one because the inputs come from two sources. It says so instead of picking a side. |
| 5 | Customer concentration (largest customer, top 5, top 10) is not in the pack. | 41% of customers are enterprise accounts (p6). An enterprise-heavy book with no concentration figures is the first data request. |

**Confirmed:** the auditor's FY2024 net sales (EUR 10.052m) agree with the deck P&L (EUR 10.05m). That is two independent origins, so the revenue figure is corroborated. The rounded headline "~EUR 12m ARR" (p1) raises no flag.

**Management questions** (tool output, word for word, from [`out/brief_kestrel.txt`](out/brief_kestrel.txt))

1. Annual recurring revenue at 2024-12-31 is EUR 15,000,000 on fintechwire-2025-02 para 3 ("annual recurring revenue") and EUR 12,060,000 on kestrel-deck-2025 p4 chart ("ARR (exit)"). These values also differ from fintechwire-2025-02 para 3: EUR 12,000,000 on kestrel-deck-2025 p1 ("ARR"); EUR 12,060,000 computed as arr = mrr * 12 from mrr EUR 1,005,000 on kestrel-deck-2025 p7 chart. Do "annual recurring revenue" and "ARR (exit)" use the same definition? If not, what does each one include?
2. Net new ARR added in period for the fiscal year 2024-01-01 to 2024-12-31 is EUR 6,800,000 computed as net_new_arr = arr[t] - arr[t-1] from arr EUR 15,000,000 on fintechwire-2025-02 para 3 and arr EUR 8,200,000 on kestrel-deck-2025 p4 chart and EUR 3,860,000 on kestrel-deck-2025 p4 ("Net new ARR"). These values also differ from fintechwire-2025-02 para 3: EUR 3,860,000 computed as net_new_arr = arr[t] - arr[t-1] from arr EUR 12,060,000 on kestrel-deck-2025 p4 chart and arr EUR 8,200,000 on kestrel-deck-2025 p4 chart; EUR 3,800,000 computed as net_new_arr = arr[t] - arr[t-1] from arr EUR 12,000,000 on kestrel-deck-2025 p1 and arr EUR 8,200,000 on kestrel-deck-2025 p4 chart. The validator cannot judge this difference: the computed value uses inputs from more than one source. Can you confirm the correct value?
3. Net revenue retention for the fiscal year 2024-01-01 to 2024-12-31 is 89% on p11 ("Net revenue retention"), below Gross revenue retention 93% on p11 ("Gross revenue retention"). The rule nrr_ge_grr (nrr >= grr) does not allow this. Which value is wrong, or do the two use a different scope or definition?
4. Largest customer share of revenue is not in the pack, and the pack does not give the values to calculate it. What is Largest customer share of revenue for each period that the pack reports, and how do you define it?
5. Top-10 customer share of revenue is not in the pack, and the pack does not give the values to calculate it. What is Top-10 customer share of revenue for each period that the pack reports, and how do you define it?
6. Top-5 customer share of revenue is not in the pack, and the pack does not give the values to calculate it. What is Top-5 customer share of revenue for each period that the pack reports, and how do you define it?
7. Annual recurring revenue at 2025-12-31 is planned at EUR 22,500,000 on p15 plan ("ARR"), growth of 86.6% a year from EUR 12,060,000 on p4 chart ("ARR (exit)"). Before that, from EUR 8,200,000 on p4 chart ("ARR"), Annual recurring revenue grew 47.1% a year. What causes the planned growth to be higher than the realized growth?

**Checks:** 6 held, 3 violated, 4 not checked ([full list](out/validate_kestrel.txt)).

---

## Halyard Fleet

A telematics company that sells devices and a monthly subscription per vehicle. The pack contains 62 figures from six documents. Halyard is the multi-source example: some sources support the deck, one contradicts it, one only looks like support, and one is noise.

**Source map**

| Document | Origin | Reliability (1 to 5) | What it says | What the tool does with it |
|---|---|---|---|---|
| Management deck | Halyard management | 4 | ARR EUR 19.68m, revenue EUR 21.5m, 43,600 vehicles tracked | The base pack |
| Audited accounts | Auditor | 5 | Net sales EUR 21.48m | **Supports.** Revenue is corroborated: 2 documents, 2 origins |
| Trade press (*fleetwire*) | Industry tracker, cited by the press | 2 | About 44,000 vehicles tracked | **Supports.** The vehicle count is corroborated. The tool counts the tracker as the origin, not the newspaper |
| CEO podcast | Halyard management | 3 | ARR "EUR 22m" | **Conflicts.** Management contradicts its own deck by EUR 2.32m. Same origin, so the class is *inconsistent*, not *contested* |
| Trade press (*logisticsdaily*) | Halyard management, cited by the press | 2 | ARR EUR 19.7m | **Echo.** It agrees with the deck, but it only repeats the company, so ARR is **not** corroborated |
| Forum post | Unknown | 1 | Revenue EUR 30m | **Noise.** Too unreliable to contest the deck. The tool lists it as *unresolvable* and does not call it a contradiction |

**Findings**

| # | What the tool found | Why it matters to an investor |
|---|---|---|
| 1 | The CEO said ARR was EUR 22m on a podcast. The deck says EUR 19.68m, and MRR × 12 confirms the deck. | Management gives a number 12% above its own deck in public. Ask which number the board sees. The press echo of EUR 19.7m does not settle it, because it is the same origin. |
| 2 | Follow-on from 1: the podcast ARR implies net new ARR of EUR 7.6m. The deck shows EUR 5.28m. | Growth claims built on the podcast figure are 44% too high. |
| 3 | The Q4 2024 MRR bridge does not close. Opening MRR EUR 1.560m plus the bridge lines gives EUR 1.687m. The deck closes at EUR 1.640m, a gap of EUR 47k. | The bridge shows EUR 47k more inflow than the closing MRR contains. In telematics, a common cause is new MRR counted when a contract is signed, before the devices are installed. The new-business line may be overstated. |
| 4 | Vehicles tracked exceed vehicles licensed (41,000). The deck shows 43,600, and an independent tracker shows about 44,000. | Two independent origins agree that about 2,600 to 3,000 vehicles are in use without a licence. The tracker makes the gap more credible, not less. Either there is unbilled usage (revenue upside and a billing-control question), or the counts use different scopes. |
| 5 | "Recurring revenue EUR 18.9m" (p2 executive summary) matches none of ARR (EUR 19.68m), recognised revenue (EUR 21.5m) or subscription revenue (EUR 16.4m). | The headline figure on the summary page has no definition. Ask what it includes. |
| 6 | No retention figures: NRR, GRR, renewal rate and cohort NRR are all missing. | The pack shows logo churn but no revenue retention. You cannot tell if existing fleets grow or shrink their spend. |
| 7 | A forum post says revenue is EUR 30m. | The deck and the auditor agree on EUR 21.5m. The tool shows the claim but cannot judge it with a reliability-1 source. An analyst can close this question without management. |

**Correctly not checked:** devices and services are 22% of revenue, so revenue (EUR 21.5m) is above ARR (EUR 19.68m). The rule "ARR ≥ revenue" applies only when non-recurring revenue is below 10%. The tool records the rule as *not checked* and gives the reason. It does not raise a false alarm.

**Management questions** (tool output, word for word, from [`out/brief_halyard.txt`](out/brief_halyard.txt))

1. Annual recurring revenue at 2024-12-31 is EUR 22,000,000 on halyard-ceo-podcast-2025-02 min 14 ("ARR") and EUR 19,680,000 on halyard-deck-2025 p4 chart ("ARR"). These values also differ from halyard-ceo-podcast-2025-02 min 14: EUR 19,700,000 on logisticsdaily-2025-02 para 1 ("ARR"); EUR 19,680,000 computed as arr = mrr * 12 from mrr EUR 1,640,000 on halyard-deck-2025 p7 chart. Which value is correct, and what explains the difference of EUR 2,320,000?
2. The MRR bridge for the quarter 2024-10-01 to 2024-12-31 does not close. Opening MRR EUR 1,560,000 (p7 chart) plus new EUR 120,000 (p12 waterfall), expansion EUR 41,000 (p12 waterfall) and reactivation EUR 0 (p12 waterfall), minus contraction EUR 12,000 (p12 waterfall) and churned EUR 22,000 (p12 waterfall), gives EUR 1,687,000. The stated closing MRR is EUR 1,640,000 (p7 chart). The bridge overstates the closing MRR by EUR 47,000. Which bridge line or which closing value is wrong?
3. Net new ARR added in period for the fiscal year 2024-01-01 to 2024-12-31 is EUR 7,600,000 computed as net_new_arr = arr[t] - arr[t-1] from arr EUR 22,000,000 on halyard-ceo-podcast-2025-02 min 14 and arr EUR 14,400,000 on halyard-deck-2025 p4 chart and EUR 5,280,000 on halyard-deck-2025 p4 ("Net new ARR"). These values also differ from halyard-ceo-podcast-2025-02 min 14: EUR 5,280,000 computed as net_new_arr = arr[t] - arr[t-1] from arr EUR 19,680,000 on halyard-deck-2025 p4 chart and arr EUR 14,400,000 on halyard-deck-2025 p4 chart; EUR 5,300,000 computed as net_new_arr = arr[t] - arr[t-1] from arr EUR 19,700,000 on logisticsdaily-2025-02 para 1 and arr EUR 14,400,000 on halyard-deck-2025 p4 chart. Which value is correct, and what explains the difference of EUR 2,320,000?
4. Recognised revenue (IFRS/K3) for the fiscal year 2024-01-01 to 2024-12-31 is EUR 30,000,000 on forum-thread-2025-01 post 3 ("revenue") and EUR 21,500,000 on halyard-deck-2025 p8 P&L table ("Total revenue"). These values also differ from forum-thread-2025-01 post 3: EUR 21,480,000 on halyard-accounts-fy2024 note 3 ("Net sales"). The validator cannot judge this difference: forum-thread-2025-01 post 3 comes from a source with reliability 1. Can you confirm the correct value?
5. "Recurring revenue" for the fiscal year 2024-01-01 to 2024-12-31 is EUR 18,900,000 on p2 executive summary. It differs from each candidate metric: Annual recurring revenue at 2024-12-31 EUR 19,680,000 on p4 chart ("ARR"); Recognised revenue (IFRS/K3) EUR 21,500,000 on p8 P&L table ("Total revenue"); Subscription revenue EUR 16,400,000 on p5 ("Subscription revenue"). Which metric does "Recurring revenue" mean, and how is it defined?
6. Seats in use at 2024-12-31 is 44,000 on fleetwire-2025-04 para 4 ("vehicles tracked"), above Seats contracted 41,000 on halyard-deck-2025 p6 ("Licensed vehicles"). The rule seats_active_le_seats_licensed (seats_active <= seats_licensed) does not allow this. Which value is wrong, or do the two use a different scope or definition?
7. Seats in use at 2024-12-31 is 43,600 on p6 ("Vehicles tracked"), above Seats contracted 41,000 on p6 ("Licensed vehicles"). The rule seats_active_le_seats_licensed (seats_active <= seats_licensed) does not allow this. Which value is wrong, or do the two use a different scope or definition?
8. Gross revenue retention is not in the pack, and the pack does not give the values to calculate it. What is Gross revenue retention for each period that the pack reports, and how do you define it?
9. Net revenue retention is not in the pack, and the pack does not give the values to calculate it. What is Net revenue retention for each period that the pack reports, and how do you define it?
10. NRR of a named cohort at month 12 is not in the pack, and the pack does not give the values to calculate it. What is NRR of a named cohort at month 12 for each period that the pack reports, and how do you define it?
11. Contracts renewed divided by contracts up for renewal is not in the pack, and the pack does not give the values to calculate it. What is Contracts renewed divided by contracts up for renewal for each period that the pack reports, and how do you define it?

**Checks:** 3 held, 4 violated, 3 not checked ([full list](out/validate_halyard.txt)).

---

## Pinewick Security

An enterprise company growing 45% a year, with NRR of 124%. The pack contains 65 figures, and it is the clean control: nothing is planted.

**Findings:** none. **Questions:** none. **Checks:** 9 held, 0 violated.

Pinewick shows that the tool stays quiet when a pack is coherent. These decoys look suspicious, but each one is correct:

| Decoy | Why the tool raises no flag |
|---|---|
| Headline "EUR 45m ARR" against EUR 45.0m in the ARR chart | The headline is rounded, and the gap is inside its printed precision. |
| A press article repeats the EUR 45m ARR | The article cites the company. That is one origin, so the figure is not corroborated and there is no contradiction. |
| The FY2025 plan of EUR 63m ARR | It implies 40% growth against 45% realised: a slowdown, not a hockey stick. |
| Monthly logo churn 0.5% against annual churn 6.0% | 0.5% is 6.0 / 12. The compound rate would be 0.51%. At one decimal, the printed figure cannot prove the error, so the tool does not claim it. |
| Revenue for DACH and for the Nordics | Two regions are two facts, not a conflict. |

The auditor's FY2024 net sales (EUR 38.61m) corroborate the deck (EUR 38.6m).

---

## Peer view

The tool works on one company at a time. This table is put together by hand from the three fact tables, so that the three companies can be compared. "As reported" means the figure in the deck, before any of the questions above are answered.

| | Kestrel | Halyard | Pinewick |
|---|---|---|---|
| ARR, Dec 2024 (EUR m) | 12.06 | 19.68 | 45.00 |
| ARR growth 2024 | 47% | 37% | 45% |
| NRR, as reported | 89%, *contradicted by GRR* | *not disclosed* | 124% |
| GRR | 93% | *not disclosed* | 95% |
| Annual logo churn | 11.0% | 7.5% | 6.0% |
| Top-10 customer share | *not disclosed* | 24% | 18% |
| Recurring share of revenue | 95% | 78% | 96% |
| Net burn, Dec 2024 (EUR k a month) | 240 | 410 | 120 |
| Burn multiple (net burn × 12 / net new ARR) | 0.75 | 0.93 | 0.10 |
| Revenue corroborated by an independent origin | Yes | Yes | Yes |
| Sources that contradict the deck | Press (ARR +24%) | CEO podcast (ARR +12%) | None |
| Questions for management | 7 | 11 | 0 |

**How to read it.** On the reported figures, Kestrel grows fastest of the two smaller companies and burns efficiently. But its retention figure contradicts itself, its plan almost doubles its growth rate, and its press figure is 24% above its deck. Halyard's figures cannot be compared on retention at all, and its CEO quotes a higher ARR in public than the deck shows. Only Pinewick's figures can go into a model without questions. A side-by-side table of the headline numbers alone would rank Kestrel above Halyard on growth and on burn efficiency, and would hide all of this.

## What this showcase does not show

- **Extraction.** These packs are already in the tool's fact format. In real use, the tool first reads PDF decks and text with an LLM, and that step adds its own errors. The tool keeps every extracted figure linked to its page and label, so a reviewer can check it.
- **Real-world rates.** The issues were planted, so every planted issue was found. On the internal seeded-error corpus (27 cases), the detection rate is 100% and the false-positive rate is 0%. Real packs are less tidy.
- **Judgement.** The tool asks questions. It does not decide which number is right. Two values that disagree stay as two values ("never average a conflict").

## Run it yourself

```bash
export FACT_LEDGER_DATABASE_URL=sqlite:///data/showcase.db
uv run alembic upgrade head
for c in kestrel halyard pinewick; do
  uv run fact-ledger facts load docs/showcase/b2b_saas/packs/$c.yaml
done
uv run fact-ledger brief kestrel --sector b2b_saas
uv run fact-ledger validate kestrel --checks
```
