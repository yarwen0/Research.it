# Retrieval benchmark

Question answering is only as good as the passages it is handed. This
directory measures whether the right passage comes back, and is what chose
the shipped retrieval configuration.

```bash
python -m evals.retrieval.run                 # score from cached embeddings
python -m evals.retrieval.run --show-misses   # what the default got wrong
python -m evals.retrieval.run --refresh       # embed anything new (needs Ollama)
```

## Method

The corpus is the three papers in [`examples/docs`](../../examples/docs) —
Stacked Hourglass, Batch Normalization and DreamPose3D — chunked by the
production chunker into 138 passages and embedded the way the indexer embeds
them, title and section headers included.

[`questions.json`](questions.json) holds 35 questions of three kinds:

| Kind | Count | Example |
|---|---:|---|
| lookup | 14 | *What learning rate was the stacked hourglass network trained with?* |
| conceptual | 17 | *Why can these networks tolerate much larger step sizes during optimization?* |
| cross-paper | 4 | *Which optimizers do the papers train with?* |

Conceptual questions are deliberately phrased away from the paper's wording —
"step sizes" for learning rates, "mirrored" for flipped — since a question that
repeats the passage word for word tests nothing but string matching.

Each question is labelled with short evidence phrases, not chunk ids, so the
labels survive a change to chunking. A passage answers a question when it
comes from a labelled paper and contains one of that paper's phrases; phrases
within a paper are alternatives, and a cross-paper question needs every paper.
`check_labels` fails the run if any phrase matches no passage, so a broken
label cannot pass for a retrieval miss.

Metrics: **hit@k**, the share of questions with an answering passage in the
top k; **MRR**, mean reciprocal rank of the first one; **coverage@k**, the share
of a question's answer-holding papers represented in the top k.

Embeddings come from [`embeddings.npz`](embeddings.npz), computed once with
`nomic-embed-text` through Ollama and committed, so CI scores real embeddings
with no model or network. They are stored as float16 — what pgvector's
`halfvec` would hold — which moves a cosine score by about 1e-3.

## Results

All variants use 50 candidates per list and Reciprocal Rank Fusion (k = 60).

| Variant | hit@1 | hit@3 | hit@5 | hit@10 | MRR | coverage@10 |
|---|---:|---:|---:|---:|---:|---:|
| **hybrid, cap 5 (shipped)** | **0.743** | **0.886** | **0.914** | 0.943 | 0.810 | 0.929 |
| dense | 0.571 | 0.886 | 0.914 | 0.943 | 0.717 | 0.914 |
| lexical (BM25) | 0.571 | 0.800 | 0.886 | 0.914 | 0.701 | 0.886 |
| hybrid, cap 3 | 0.743 | 0.886 | 0.886 | 0.914 | 0.804 | 0.900 |
| hybrid, no cap | 0.743 | 0.886 | 0.914 | 0.971 | 0.815 | 0.943 |
| hybrid, no title/section headers | 0.714 | 0.857 | 0.886 | 0.914 | 0.771 | 0.886 |
| hybrid, no task hints | 0.743 | 0.886 | 0.886 | 0.914 | 0.794 | 0.886 |

**Read with the sample size in mind:** 35 questions, so one question moves a
rate by 0.029. Most rows differ by one or two questions. The finding that
survives that is the first column.

### Hybrid puts the answer first

Dense and hybrid retrieve the same passages by rank 5 and 10. What fusion buys
is order: the answering passage is ranked first for 26 of 35 questions,
against 20 for dense and 20 for BM25. For question answering, which reads the
top few passages, that is the number that matters.

The two lists fail differently. BM25 is strongest on lookups (MRR 0.827 against
dense's 0.762) — "2.5e-4", "5003", "BN-x30" are exact strings — and weakest
across papers, where one paper's vocabulary floods the list. Dense is the
reverse. Fusion takes the better of each per question.

### The per-paper cap, and why it is 5

Without a cap, one paper's near-duplicate passages fill the list. Removing it
looks slightly better overall here, but only because 31 of the 35 questions
are about a single paper. On the four cross-paper questions — the ones a cap
exists for — coverage@10 falls from 0.875 to 0.500. A cap of 3 keeps that
coverage but starves single-paper questions of the passages they need. 5 keeps
the first and recovers most of the second.

### Both embedding details pay for themselves

Embedding each passage with its paper title and section in front of it, and
telling the model whether it is embedding a document or a query, are both
cheap and both measurable. Without the headers the default loses a question
at every cutoff and 0.039 MRR; without task hints it loses one at k = 5 and
k = 10 and 0.016 MRR. Neither costs anything at query time.

### What it still misses

At k = 5 the shipped configuration misses three:

| Question | Why |
|---|---|
| *Does normalizing activations make a separate regularizer unnecessary?* | Four passages answer it, all phrased around "Dropout", which the question never names. |
| *What do the authors plan to try next to make poses more realistic?* | The answer says "future research" and "pose realism"; the question says "try next" and "realistic", and BM25 does no stemming. |
| *Which optimizers do the papers train with?* | Found at rank 9: optimizer names are single tokens buried in implementation paragraphs. |

## What this does not measure

Whether the shipped settings are best on a corpus of real size. Three papers
are enough to compare strategies; they are not enough to tune RRF's constant
or the candidate count, which were left at their textbook values rather than
fitted to 35 questions.
