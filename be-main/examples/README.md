# Backend examples

Sample data plus standalone scripts that exercise individual stages of the
pipeline. The scripts live in the backend root (`be-main/`) and are meant to be
run from there, so their relative paths into this folder resolve.

## Sample data (this folder)

- `sample_corpus.json` — a small normalized corpus used by the gap finder.
- `docs/*.txt` — raw paper text used by the extraction examples
  (`batch_normal.txt`, `dreampose.txt`, `hourglass.txt`).
- `results.json` — an example of processed pipeline output.

## Scripts (in `be-main/`)

| Script | What it does | Provider key |
|--------|--------------|--------------|
| `gap_find_example.py` | Runs the symbolic gap finder over `sample_corpus.json` and prints detected gaps and title conditions. | Not needed |
| `extractor_example.py` | Extracts and normalizes parameters from a document in `docs/`. | Yes (OpenRouter) |
| `reference_extract_example.py` | Parses references from a citation string via the LLM fallback extractor. | Yes (Gemini) |

## Running

```bash
cd be-main

# Pure — no provider key required:
python gap_find_example.py
python gap_find_example.py --top-k 5 --strict

# Require a configured provider:
python extractor_example.py dreampose      # extracts examples/docs/dreampose.txt
python reference_extract_example.py
```
