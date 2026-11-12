# Spec — Milestone 2: API client

Decisions: [ADR 0003](../adr/0003-reading-changing-data.md). Conventions of the API: [ADR 0002](../adr/0002-mock-api-conventions.md).

## Layout

```
src/ops_client/
    __init__.py      # exports OpsClient, the errors, the models; __version__ = "0.1.0"
    errors.py        # OpsError base; AuthError(401), NotFoundError(404), ValidationError(422),
                     # ConflictError(409, .current: dict, .error: str), RateLimitError (retries used up),
                     # ServerError (5xx after retries), IncompleteWindowError (.window, .expected, .got)
    auth.py          # get_token() -> str: keyring("ops-console", "api_token") then env OPS_API_TOKEN, else AuthError
    models.py        # pydantic v2 models: User, Project, Task, TimeEntry, Approval (fields = M1 schema)
    http.py          # request with retries (ADR 0003 §4); `sleep` and `rng` injectable for tests
    paging.py        # iter_pages(), read_windowed(), naive_read_by_updated_at()
    client.py        # OpsClient facade
tests/
    test_client_*.py # new files only; do not change the M1 tests
```

## `OpsClient`

```python
OpsClient(base_url="http://127.0.0.1:8000", token=None, http=None, max_retries=5,
          sleep=time.sleep, rng=None)
```
- `token=None` → `auth.get_token()`. `http` = an injected `httpx.Client` (tests pass Starlette's `TestClient(app)`,
  which is an `httpx.Client`); otherwise the client creates one with a 30 s timeout.
- `repr(client)` and log messages never contain the token.
- Methods:
  - `health() -> dict`
  - `get(resource, id) -> Model`
  - `list(resource, **filters) -> Iterator[Model]` — all pages, `per_page=200`, order `id:asc`.
  - `extract(resource, start: date, end: date, window_days=7) -> list[Model]` — ADR 0003 §1–3 over
    `created_between`; windows cover start to and including end; result sorted by id.
  - `patch_project(id, version, **changes) -> Project` — 409 → `ConflictError`.
  - `approve(id, version, approver_id) -> Approval`, `reject(...)` — same.
- Resource names are the API's: users, projects, tasks, time_entries, approvals; unknown → `ValueError` before any request.

## Retries (`http.py`)
- 429: sleep `min(int(Retry-After or 1), 30)`; 5xx / `httpx.TransportError`: sleep `min(0.5 * 2**attempt, 30) * (0.5 + rng.random())`.
- After `max_retries` retries: `RateLimitError` (429) or `ServerError` (5xx/transport).
- 401/404/409/422 map to their error at once (no retry). Each retry logs one line at INFO (method, path, status,
  attempt, wait) without headers.

## Paging (`paging.py`)
- `read_windowed`: per window, read pages until `page > page_count`; collect by id keeping the highest `version`;
  compare unique count to the first page's `meta.count`; on mismatch re-read the window (max 3 attempts in total),
  then `IncompleteWindowError`. Log one INFO line per window (window, pages, rows).
- `naive_read_by_updated_at(client, resource)`: offset paging, `order=updated_at:asc`, `per_page=200`, no checks.
  Exists only to demonstrate the failure; docstring says so.

## Tests (must pass with the M1 tests: `pytest`, and `ruff check .` clean)
1. `health()` and `get()` return the right types; unknown resource → `ValueError` with no request sent.
2. `list("projects")` returns all 25 projects as `Project` models.
3. Retry on 429: app with `fault_rate=0.5`, `rng_seed=1` → `list("users")` returns all 40; fake `sleep` was called
   with 1 at least once; no real sleeping in any test.
4. Retries used up: `fault_rate=1.0` → `RateLimitError`; fake sleep called exactly `max_retries` times.
5. 401 → `AuthError` at once (sleep not called). 404 → `NotFoundError`.
6. Windowed extract, no chaos: `extract("time_entries", 2026-01-01, 2026-07-15)` ids == all ids in the db.
7. **Windowed extract under chaos** (`chaos_rows=20`): same ids as test 6, and each returned row has the highest
   version seen.
8. **Naive paging skips rows under chaos** (`chaos_rows=20`): `naive_read_by_updated_at` misses at least one id
   that exists in the db. Name: `test_naive_updated_at_paging_skips_rows`.
9. Window check: a wrapped `http` that drops one row from one page → after 3 attempts `IncompleteWindowError` with
   `expected` and `got`.
10. `patch_project` with a stale version → `ConflictError` with `.current["version"]` = the stored version; correct
    version → updated `Project`.
11. Token: keyring value wins over env (monkeypatch `keyring.get_password`); keyring `None` → env; neither →
    `AuthError`; the token string is absent from `repr(client)` and from captured logs (`caplog`) in tests 3 and 6.
12. `extract` with `start > end` → `ValueError`.

## Out of scope
README changes (the lead writes them), the console (M3), CI files.
