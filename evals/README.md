# Evals

Correctness is measured on a **seeded-error corpus**, not by an LLM that judges prose. See section 7 of the architecture document. Owner: eval-engineer.

## Layout

- `corpus/<case>/` contains one synthetic investment pack and a `manifest.yaml`.
- `manifest.yaml` lists the planted defects. A clean control case has `defects: []`.
- `harness.py` runs the system on each case and scores the flags.
- `baseline.json` holds the accepted scores. `make eval` fails when a change is worse than the baseline by more than `margin`.

## Manifest format

```yaml
defects:
  - defect_type: definitional_switch   # or arithmetic, removed_expected_metric, denominator_drift,
    location: "nimbus-deck-2025#p11"   #    projection_break, corroboration,
                                       #    cross_origin_contradiction, basis_gap
    expected_class: definitional
    note: "ARR on p4 and recognised revenue on p11 give different growth."
```

A case is `corpus/<case>/transcript.yaml` (the `facts load` format) and `manifest.yaml`. A row can override `origin_id` and `document_id`, so one transcript can hold a deck and a press article.

A seeded error is a clean pack with one planted change. So a manifest can name a `base` case:

```yaml
base: clean-nimbus
defects: [...]
```

The pack is then the rows of the base transcript, with the rows of the case transcript on top. A case row replaces the base row with the same `observation_id`. The case transcript holds only the planted rows and the rows it changes, so a review of the case is a review of the planted change.

A manifest can also remove base rows and name a sector (story S4-01):

```yaml
base: clean-nimbus
sector: b2b_saas
remove: [nimbus-20]
defects: [...]
```

`remove` lists the `observation_id` of each row to drop after the merge. An id that is not in the pack raises an error, so a typo never scores silently. `sector` is the argument of `patterns`. With no `sector`, the absence check does not run. A case reads only its own manifest, not the manifest of its base. So only `clean-nimbus` and `absence-grr` run the absence check. A case with no row of its own holds a transcript with `defaults: {}` and `observations: []`.

A manifest can name a synthetic PDF `deck` and its recorded LLM responses. The case then has no transcript. The harness gets the rows from `extract_deck` with `replay`, so a wrong extraction that adds a finding is a false positive. Paths are relative to the repository root. The location is the locator that the extractor writes (`p<N>`, the PDF page index). One page holds many values, so each planted defect also gives `value`: the value of the subject row, as the extractor writes it (`"7450000"`). A flag matches only when its subject has that value. The manifest then starts with the line `# Synthetic corpus case. No real company data.`, as a transcript does.

```yaml
deck:
  pdf: tests/fixtures/decks/nimbus-pdf-2025.pdf
  responses: tests/fixtures/decks/nimbus-pdf-2025.responses.json
  source: {entity_id: nimbus, origin_id: nimbus-management, document_id: nimbus-pdf-2025,
           reliability: 4}
defects: [...]
```

## From a finding to a flag

`harness.py` runs the domain validator and then `patterns` on the rows of each case. Each finding and each absence gives one flag. The harness matches a flag to a planted defect on `(defect_type, location)`. In a deck case, it also matches on `value`. Flags and planted defects are counted as multisets: two findings at one location are two flags. So an extra finding at the location of a planted defect is a false positive, and it is never hidden.

| Finding | `defect_type` |
|---|---|
| Divergence, Inconsistent (direct or computed path) | `arithmetic` |
| Divergence, Definitional | `definitional_switch` |
| Ambiguity, and label conflict | `definitional_switch` |
| Basis gap (S4-04) | `basis_gap` |
| Divergence, Contested | `cross_origin_contradiction` |
| Divergence, Unresolvable | `unresolvable` (no case plants it, so it is always a false positive) |
| Invariant `customers_paying_le_users_registered`, `seats_active_le_seats_licensed` | `denominator_drift` |
| Invariant `nrr_ge_grr` | `arithmetic` |
| Invariant `arr_ge_revenue_recognised` | `definitional_switch` |
| MRR bridge residual | `arithmetic` |
| Projection of `arr` (S4-02) | `projection_break` |
| Absence (S4-01) | `removed_expected_metric` |
| Corroborated comparison (no finding) | `corroboration` |

The mapping has no fallback. A new finding kind fails the eval until the mapping names it.

Corroborated gives no finding, so the harness also reads the Corroborated comparisons (story S5-04). It raises one `corroboration` flag for each fact (entity, metric, period, qualifier) and each pair of effective origins. One echo often meets several paths of one fact (p4, p1, MRR x 12), and it is one error. A computed path holds the origins of all its inputs, so both sides of a comparison are expanded into pairs of one origin and one origin. A manifest plants a true corroboration as a defect. So an echo that reaches Corroborated is an unplanted `corroboration` flag: a false positive.

`location` is `<document_id>#<locator>`, from one path of the finding. An absence has no path, so its location is `<entity_id>#<metric_id>`. A corroboration has no one row, so its location is the fact and the pair:

| Finding | Location |
|---|---|
| Divergence | The subject: the value that differs from the most other values. A computed subject gives its first input. |
| Ambiguity | The ambiguous row |
| Label conflict | The matched row with the latest period |
| Basis gap | The reported row |
| Invariant | The row of the first term (`customers_paying`, `seats_active`, `nrr`, `arr`) |
| MRR bridge | The locator that most of the seven values share. On a tie, the locator of the closing MRR. |
| Projection | The projection row |
| Absence | The entity and the expected metric that it does not show, for example `nimbus#grr` |
| Corroboration | `<entity_id>#<metric_id>#<period_end>#<origin_a>+<origin_b>`, with the two origins sorted, for example `nimbus#revenue_recognised#2024-12-31#nimbus-audited-accounts+nimbus-management`. Two qualifiers at one location give two flags. |

**Rule for case authors.** In a divergence case, put at least one more value on the correct side (a headline figure, or MRR x 12). The planted value is then the subject by count, not by a tie-break. A case that keeps an ambiguous row must do the D2.6 match test of `validator.py` by hand: an inferred row can give a divergence finding.

Not in scope yet: `echo` (origin resolver, S5). No case plants it. An echo is not a defect type: it scores as an unplanted `corroboration` (S5-04).

## Rules

1. Corpus data is synthetic. Never put real company data here.
2. Seeds are fixed. The same corpus and code give the same numbers.
3. Change `baseline.json` only in a pull request that explains the change.

## Run

```sh
make eval
```
