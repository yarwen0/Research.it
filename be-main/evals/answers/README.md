# Answer quality

The retrieval benchmark measures whether the right passage comes back. This
one measures what a model does with it: whether the answer states the right
fact, whether it cites the passage that holds it, and whether it declines
when the papers do not say.

```bash
LLM_PROVIDER=ollama python -m evals.answers.run
```

Needs a model, so it is recorded here rather than gated in CI.
[`tests/test_answer_eval.py`](../../tests/test_answer_eval.py) pins the
scoring without one.

## Method

The corpus is the three example papers, indexed into a throwaway database
with the retrieval benchmark's cached document embeddings. Every question
goes through `CorpusQA` — the code `POST /api/projects/{id}/ask` runs.

[`questions.json`](questions.json) holds 26 questions:

- **18 answerable**, taken word for word from the retrieval benchmark, so
  their evidence labels are the ones its label check proves present: 14
  lookups with a crisp answer ("What initial learning rate did BN-x30 use?")
  and 4 conceptual questions. Each lists the spellings a right answer may use.
- **8 unanswerable**, on topics that appear nowhere in the three papers —
  checked with grep: carbon footprint, audio, licensing, dollar cost,
  reinforcement learning, COCO, LiDAR, Kinect.

Verdicts per question: an answerable question is **correct** when the answer
states the expected fact and does not decline, and **supported** when a
passage it cites contains the question's evidence. An unanswerable question
is handled correctly when the answer declines.

## First run

qwen2.5:7b with nomic-embed-text through Ollama, on the development machine:

| | |
|---|---:|
| Answerable: states the expected fact | **0.833** (15/18) |
| Answerable: a cited passage holds the evidence | 0.278 (5/18) |
| Answerable: declined although answerable | 0.056 (1/18) |
| Unanswerable: declined | **1.000** (8/8) |
| Grounded: cites a supplied source, or declines | 0.615 (16/26) |
| Citations of sources never supplied | 0 |
| Latency p50 / p95 | 12.2 s / 17.3 s |
| Mean prompt size | 2,366 tokens |

One run: a model's answers vary between runs, so read every rate as carrying
a question or so of noise.

### What it found

- **Declining works on this set.** All eight unanswerable questions were
  declined, and one answerable one was: the passage that answers it is a
  garbled results table, and the model replied "sync" and gave up.
- **Citations were the weak point.** Ten answers cited nothing, nine of them
  correct — "Training takes about 3 days on a 12 GB NVIDIA TitanX GPU."
  The prompt asked for inline `[S1]` markers; a 7B model treated that as
  optional.
- **Two misses start upstream of the model.** One answer came from the wrong
  paper, for a question whose passage the retrieval benchmark also fails to
  rank in the top ten. Another read step counts off a table instead of the
  sentence that states "14 times fewer".

### What changed because of it

Citations are now a required field in the answer's JSON schema, for `/ask`
and for the assistant's writer, merged with any inline markers and validated
the same way. Constrained decoding can enforce a field; it cannot enforce a
convention in prose.

## After the change

The same questions and model, run twice after citations became required.
Both runs gave identical rates; [`results.json`](results.json) holds the
second.

| | Before | After |
|---|---:|---:|
| Answerable: states the expected fact | 0.833 (15/18) | **0.889** (16/18) |
| Answerable: a cited passage holds the evidence | 0.278 (5/18) | **0.889** (16/18) |
| Answerable: declined although answerable | 0.056 (1/18) | 0 (0/18) |
| Unanswerable: declined | 1.000 (8/8) | 1.000 (8/8) |
| Grounded: cites a supplied source, or declines | 0.615 (16/26) | **1.000** (26/26) |
| Citations of sources never supplied | 0 | 0 |

A jump that size needs checking: an answer that cites all eight passages it
was given is "supported" whatever it says. So the benchmark now records how
widely each answer cites. Answers cited **1.38 of 8 passages on average, and
none cited all eight**. Answerable questions cited one passage (9), two (7)
or four (2). The gain is real, not a model citing everything.

The two remaining misses are the two that start upstream of the model: the
passage retrieval does not rank, and the step count read off a table. The
answer that declined over a garbled table now answers it.

Latency is not compared. The same machine gave a p50 of 12.1 s on the first
run after the change and 3.9 s on the second, which says more about the
laptop than the pipeline.
