# Gap detection evaluation

The core claim of this project is that it finds research gaps. This directory
measures whether it does.

```bash
python -m evals.run_eval                      # score the shipped settings
python -m evals.run_eval --show-misses        # list what it got wrong
python -m evals.run_eval --sweep              # search the threshold grid
python -m evals.run_eval --top-k-per-type 40  # vary the output cap
```

## Method

`corpus.json` holds 18 papers across three problems (3D pose estimation, human
mesh reconstruction, hand pose estimation), in the same canonical shape the
extraction pipeline emits.

`labels.json` holds attributes the detector never sees: what input each method
consumes, what each dataset provides, and which body region each concerns.

Ground truth follows from that split. A **transfer gap** — "method M has not
been tried on dataset D for problem P" — is only genuine if the pairing could
actually be run. Three ways it cannot be:

- the dataset does not provide the method's input (a temporal model needs
  video; MPII is static images);
- the method is specific to a region the dataset does not cover (an SMPL body
  regressor cannot consume a hand dataset);
- the dataset covers a different region than the problem studies.

None of this is inferable from the corpus, which is the point: the detector
works purely from co-occurrence counts, so the distance between its output and
these labels is exactly the cost of having no notion of type compatibility.

Limitation and future-work gaps are hand-labelled, with the reasoning for each
recorded next to it in `labels.json`.

**What this does and does not measure.** It measures whether the detector
recovers structure that is present in a corpus and avoids proposing
combinations that are impossible. It does not measure whether a surfaced gap is
research that anyone should actually do — that needs domain experts and a real
corpus, and is the obvious next step.

## Results

Reproducible via the commands above. 18 papers, 69 gaps in ground truth.

### Output cap is the dominant lever

`top_k_per_type` bounds how many gaps of each type are returned, and the API
passes 5:

| `top_k_per_type` | Precision | Recall | F1 |
|---:|---:|---:|---:|
| **5** (shipped) | **0.722** | **0.188** | **0.299** |
| 10 | 0.679 | 0.275 | 0.392 |
| 15 | 0.658 | 0.362 | 0.467 |
| 20 | 0.604 | 0.420 | 0.496 |
| 30 | 0.515 | 0.507 | 0.511 |
| **40** | 0.489 | 0.623 | **0.548** |
| 50 | 0.435 | 0.681 | 0.531 |

The shipped setting is the most precise configuration measured and the worst by
F1: it returns 18 of 69 genuine gaps. Whether that is wrong depends on the
product — for a UI surfacing a handful of suggestions, precision is arguably
the right thing to buy. It was not, however, a decision anyone made with these
numbers in hand.

### Per type, at the shipped setting

| Gap type | Precision | Recall | F1 |
|---|---:|---:|---:|
| `method_transfer` | 0.800 | 0.125 | 0.216 |
| `dataset_transfer` | 0.800 | 0.125 | 0.216 |
| `limitation_gap` | 0.750 | 1.000 | 0.857 |
| `future_work_gap` | 0.500 | 1.000 | 0.667 |

Limitation and future-work detection find everything they should; the transfer
detectors are recall-bound by the cap.

### The threshold knobs do almost nothing

A 486-configuration sweep over all five thresholds produced a best F1 of 0.488
at `top_k_per_type=25` — matching the default. `loose_mode=True` clamps every
threshold in the constructor:

```python
if self.loose_mode:
    self.method_transfer_min_score = 0
    self.dataset_transfer_min_score = 0
    ...
```

so tuning them while loose mode is on changes nothing. The API enables loose
mode, which makes the five threshold parameters it passes inert.

### Every false positive is a known blind spot

At the shipped setting the detector produces five spurious gaps, and each one
has the same cause:

| Spurious gap | Why it is wrong |
|---|---|
| `temporal_smoothing` → `mpii` (×2 types) | MPII is static images. There is no temporal signal to smooth. |
| `add_temporal_modeling` | Already delivered by `temporal_smoothing` in three papers — under a different name, which the literal label match misses. |
| `faster_sampling` | An efficiency ask against known methods, not an unexplored direction. |
| `interaction_ambiguity` | Only arises on two-hand datasets, so it is not an open problem for the field. |

Two concrete fixes follow: give methods and datasets type signatures and filter
incompatible pairings before scoring, and resolve future-work labels against
method names semantically rather than by string equality.

## What this caught

**Gap detection was non-deterministic.** The first runs of this harness gave F1
between 0.425 and 0.520 on identical input and configuration.

Scores are a `min()` over three small counts, so ties are the norm rather than
the exception. The finder iterated over `set` objects and sorted on score
alone, so which tied gaps survived the `top_k` cut came down to the order
candidates happened to leave a set — and Python randomises string hashing per
process. Same corpus, different research suggestions, run to run.

Fixed in `gap_finder.py` by sorting candidate iteration and breaking ties on
gap identity. `tests/test_gap_finder_determinism.py` runs the finder under
several `PYTHONHASHSEED` values to keep it fixed.

## Next steps

- Type signatures on methods and datasets, so impossible pairings are filtered
  before scoring rather than surfaced and ranked.
- Semantic matching of future-work labels against realised methods.
- A real corpus with expert labels, to measure research value rather than
  structural consistency.
- Rank by something better than `min()` of three counts — it ties constantly,
  which is what made the ordering bug invisible until it was measured.
