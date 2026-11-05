# Security

Research.it accepts untrusted input in three places that are worth calling out,
and what constrains each.

## Untrusted LaTeX → `POST /api/latex/compile`

The editor posts arbitrary LaTeX to be compiled. LaTeX is a full programming
language with filesystem access, so this is the sharpest edge in the app.

| Guard | What it stops |
|---|---|
| `-no-shell-escape` | `\write18{...}` running shell commands. Usually the default, but a local `texmf.cnf` can re-enable it, so it is passed explicitly. |
| `openin_any=p` | `\input{/etc/passwd}` pasting server files into the returned PDF. |
| `openout_any=p` | Writing outside the compilation directory. |
| Throwaway temp dir | Compilation artifacts never touch `data/` and are deleted afterwards. |
| 512 KB input cap | Trivially large documents exhausting the worker. |
| 60 s per-pass timeout | Non-terminating documents pinning a thread. |

See [`be-main/utils/latex.py`](be-main/utils/latex.py).

Note the residual risk: this hardens TeX, it does not sandbox the process. For
a public deployment taking untrusted documents at volume, run the compiler in
its own container with no network and a read-only root filesystem.

## Client-supplied paths → `POST /api/create_review`

`saved_filepath` is a value the client received from an earlier response and
echoes back, which makes it untrusted. Without a check, `"/etc/passwd"` would
be read and returned.

`resolve_data_path()` ([`be-main/utils/paths.py`](be-main/utils/paths.py))
resolves the path — following symlinks first, so a link planted inside `data/`
cannot be used to escape — and rejects anything landing outside the data
directory. It is applied twice on purpose: once as a Pydantic validator so the
request fails with 422 before any work starts, and once at the `open()` call
so the invariant holds regardless of caller.

## Untrusted paper text → LLM prompts

Every PDF the pipeline reads was written by someone else, and its text ends
up inside prompts — extraction, references, and every grounded answer. A
paper can contain "ignore your instructions" as easily as it contains an
abstract.

| Guard | What it stops |
|---|---|
| Passages that read as instructions to a model are withheld from every prompt and reported; `/search` marks them instead ([`retrieval/screening.py`](be-main/retrieval/screening.py)) | Overrides, role hijacks, prompt exfiltration and hidden reviewer instructions reaching a model at all |
| Passages fenced in `<source>` tags, with any tag inside them neutralized | Text closing its own fence and posing as instructions |
| The system prompt states sources are data, not instructions | The model obeying text it was asked to quote |
| Citations checked against the ids actually supplied | An answer citing evidence that was never retrieved |
| Structured output (JSON schema) for answers | Free-form text smuggling in fake fields |
| Every agent prompt states tool results are data | Paper text steering an agent's next tool call |
| Evidence ids assigned by tools, validated in the final answer | An agent citing evidence no tool returned |

The screen is measured on a labelled set with a held-out split
([`evals/injection`](be-main/evals/injection/README.md)). It caught 13 of 15
held-out attacks and flagged none of 20 sentences of ordinary prose or prose
that discusses and quotes attacks. Not flagging those matters as much as
catching attacks, because a corpus about LLM security quotes them constantly.
It is pattern-based, so a phrasing it has no pattern for gets through: the two
held-out misses are recorded there and deliberately left unfixed, since
patching them after reading them would only memorize the test set.

This reduces prompt injection; it does not eliminate it. A model can still be
steered by text in its context, and the answer it writes is shown to a user.
Treat answers as untrusted output and render them as text, never as HTML.

## Outside agents → `/mcp/`

The MCP endpoint gives an agent the corpus tools. What constrains it:

| Guard | What it stops |
|---|---|
| Mounted only when `MCP_API_KEY` is set | An unauthenticated MCP endpoint existing at all |
| Bearer token compared in constant time | Guessing the token byte by byte from response timing |
| Every tool read-only; no tool starts a run | An agent spending minutes of downloads and LLM budget |
| A per-client limit at the mount (`RATE_LIMIT_MCP`), checked before the token | One client flooding the tools, or guessing the token at speed |

The mount needs a limiter of its own. The API's middleware matches each
request to a route endpoint and treats a request it cannot match as exempt;
a mounted ASGI app has no endpoint, so `/mcp/` was unlimited until the gate
applied the same kind of limit itself.

DNS-rebinding protection is off for the mounted endpoint: it exists to stop a
web page from reaching a server that trusts local callers, and this one trusts
no caller without the token, which a rebound page cannot send.

## Cost and abuse → all endpoints

There is no authentication yet, so every endpoint is rate limited per client
([`be-main/rate_limit.py`](be-main/rate_limit.py)). Limits are tiered by what a
call actually costs — a research run is dozens of PDF downloads plus a long
chain of LLM requests, so it gets 5/hour against a 120/minute general budget.

Two deployment details matter:

- **`TRUST_PROXY_HEADERS`** must be on behind a proxy that overwrites
  `X-Forwarded-For` and off otherwise. Off behind a proxy, every client shares
  the proxy's address and one caller starves everyone. On without a proxy,
  `X-Forwarded-For` is spoofable and a caller mints a fresh bucket per
  request.
- **`TRUSTED_PROXY_HOPS`** replaces it behind proxies that *append* to the
  header — Google's front end does, so the Cloud Run deployment sets it to 1.
  There the left-most entry is whatever the client sent, and trusting it
  would let a caller pick its own bucket; the limiter reads the entry the
  proxy appended instead.
- **`RATE_LIMIT_STORAGE_URI`** defaults to in-memory, which is per-process.
  With N workers the effective limit is N×. Point it at Redis before scaling
  past one.

## CORS

`CORS_ORIGINS` defaults to `*` for local development. Credentialed CORS is
switched off automatically while the wildcard is in play, because Starlette
resolves `allow_origins=["*"]` plus `allow_credentials=True` by echoing back
whatever `Origin` it is given — which would let any site make credentialed
calls the moment authentication exists.

Set `CORS_ORIGINS` to your real frontend origin in production.

## Known gaps

Honest list of what is not addressed yet:

- **No authentication or per-user isolation.** Every run is anonymous, and any
  caller who knows a `project_id` can read that graph.
- **No sandbox around the LaTeX process**, only TeX-level restrictions.
- **No signed URLs** on generated artifacts.

## Reporting

Open an issue, or email the address on the commit history.
