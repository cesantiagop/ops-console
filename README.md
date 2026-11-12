# ops-console

[![CI](https://github.com/cesantiagop/ops-console/actions/workflows/ci.yml/badge.svg)](https://github.com/cesantiagop/ops-console/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

A terminal admin console for a professional-services automation (PSA) system, built to show how to read and
change business data **safely**: paging that doesn't silently skip rows, bulk changes that are previewed,
confirmed and logged, and secrets that never touch a file.

Everything runs against a bundled **mock API with synthetic data** (Faker, fixed seed): no real system, people or
numbers.

## Try it in one command

```powershell
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
ops-console --demo
```

`--demo` runs the whole stack in-process (seeded database, API, client, console): no server, no token, nothing
saved.

```
ops-console — demo (synthetic data)
 1  Health check
 2  Search projects
 3  Project detail
 4  Hours by person by week
 5  Approvals waiting
 6  Bulk change projects (CSV)
 7  Ledger
 8  Undo a run
 0  Exit
```

## What this project demonstrates

| Problem | What the code does | Proof |
|---|---|---|
| **Offset paging ordered by `updated_at` silently loses rows** when records are edited mid-read | Reads in fixed `created_at` windows, de-duplicates by id (highest version wins), checks each window's count against the API's total and fails loudly on a mismatch | `test_naive_updated_at_paging_skips_rows`: under concurrent edits the naive reader misses **~4 % of 25,414 rows**; the windowed reader misses none ([ADR 0003](docs/adr/0003-reading-changing-data.md)) |
| Rate limits and flaky servers | 429 honours `Retry-After`; 5xx/transport errors back off exponentially with jitter; other 4xx never retried | fault-injection tests with a fake clock (no real sleeping) |
| Two people editing the same record | Every row has a `version`; writes send it; a stale write gets **409** and the current row. Conflicts are surfaced, never overwritten | concurrency tests ([ADR 0002](docs/adr/0002-mock-api-conventions.md)) |
| Bulk edits from a spreadsheet | Validate the whole file first, plan against live data, preview old → new, require `APPLY <n>`, apply row by row, record every outcome in an **append-only ledger**, undo through the same path | changeset + ledger tests; [ledger sample](docs/examples/ledger-sample.md): apply, undo, and the database refusing an edit ([ADR 0004](docs/adr/0004-safe-bulk-changes.md)) |
| Money arithmetic | Integer cents end to end; CSV dollars parsed with `Decimal`; one division, rounded half-up; more than 2 decimals is an error, never rounded | report tests that fail if per-row rounding is used |
| Secrets | Token from the OS keyring, then an env var; never in files, logs or `repr` | token tests + **gitleaks** over the full history in CI |

## Architecture

```
            +-------------------+        HTTP (JSON)         +----------------------+
  user ---> |  ops_console      | --> ops_client (paging, -> |  ops_api (mock)      |
            |  menus, reports   |     retries, models)       |  FastAPI + SQLite    |
            +---------+---------+                            |  Faker seed data     |
                      |                                      +----------------------+
                      v
            changeset -> plan -> preview -> confirm -> apply -> ledger (SQLite, append-only)
```

| Package | Role |
|---|---|
| `src/ops_api` | Mock PSA API: users, projects, tasks, time entries, approvals. Opt-in fault injection: rows edited mid-read (`--chaos-rows`), random 429s (`--fault-rate`) |
| `src/ops_client` | Typed client: retries, windowed extraction, error mapping, keyring/env token |
| `src/ops_console` | Rich-based menus, pure report functions, changesets, ledger, undo |

Design decisions are recorded as ADRs in [docs/adr](docs/adr), and each milestone has a written spec in
[docs/specs](docs/specs) that its tests enforce.

## Run the mock API on its own

```powershell
python -m ops_api seed --db data/ops_api.db     # builds the synthetic database, prints row counts
python -m ops_api serve --db data/ops_api.db    # http://127.0.0.1:8000, token from OPS_API_TOKEN
```

If `OPS_API_TOKEN` is not set, the server uses the public demo token `dev-token` and prints a warning. Try it
from a second terminal, or open http://127.0.0.1:8000/docs for interactive API docs:

```powershell
curl.exe -H "Authorization: Bearer dev-token" "http://127.0.0.1:8000/v1/projects?per_page=2"
```

(`curl.exe`, not `curl`: in Windows PowerShell `curl` is an alias for `Invoke-WebRequest`. On macOS/Linux use
`curl`.) Point the console at it with `ops-console --base-url http://127.0.0.1:8000`.

## Tests and CI

```powershell
pytest            # unit + integration tests against the in-process API
ruff check .      # lint
```

GitHub Actions runs ruff and pytest on Python 3.11, 3.12 and 3.13, and scans the full git history for secrets
with gitleaks on every push. The one gitleaks exception (the public demo token) is documented in
[.gitleaks.toml](.gitleaks.toml).

## Known limitations

- **Hours by person by week** reads time entries by creation date plus 7 days of lag, then filters by work date.
  An entry created more than 7 days after the work was done would be missed. A real deployment would extract by
  the work-date filter or size the lag from data.
- Changesets cover projects only; approvals are single actions.
- The mock API uses SQLite and is single-process by design.

## License

MIT, see [LICENSE](LICENSE).
