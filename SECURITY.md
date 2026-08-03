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

## Cost and abuse → all endpoints

There is no authentication yet, so every endpoint is rate limited per client
([`be-main/rate_limit.py`](be-main/rate_limit.py)). Limits are tiered by what a
call actually costs — a research run is dozens of PDF downloads plus a long
chain of LLM requests, so it gets 5/hour against a 120/minute general budget.

Two deployment details matter:

- **`TRUST_PROXY_HEADERS`** must be on behind a proxy and off otherwise.
  Off behind a proxy, every client shares the proxy's address and one caller
  starves everyone. On without a proxy, `X-Forwarded-For` is spoofable and a
  caller mints a fresh bucket per request.
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
