# Spec — Milestone 1: mock PSA API + synthetic seed data

Conventions: [ADR 0002](../adr/0002-mock-api-conventions.md). This spec is the contract; the tests prove it.

## Layout

```
pyproject.toml            # already written; package "ops-console", src layout
src/ops_api/
    __init__.py           # __version__ = "0.1.0"
    __main__.py           # CLI: `python -m ops_api seed ...` and `python -m ops_api serve ...`
    db.py                 # sqlite3 schema + connection helpers (stdlib sqlite3, no ORM, SQL visible)
    seed.py               # Faker-based deterministic seed
    app.py                # create_app(db_path, token, chaos_rows=0, fault_rate=0.0, rng_seed=0) -> FastAPI
    queries.py            # list/get/patch SQL builders (parameterised, whitelisted columns only)
tests/
    conftest.py           # fixture: seed a temp db (seed=42) once per session; TestClient factory
    test_seed.py  test_list.py  test_get.py  test_write.py  test_faults.py
```

## Data model (SQLite)

Every table has `id INTEGER PRIMARY KEY`, `created_at TEXT`, `updated_at TEXT` (ISO UTC `Z`), `version INTEGER
NOT NULL DEFAULT 1`. Foreign keys on.

| Table | Columns (besides the common four) |
|---|---|
| `users` | `name`, `email` (Faker, `example.com/.org/.net` domains only), `title`, `department` (6 fixed fictional names), `active` (0/1), `cost_rate_cents`, `bill_rate_cents` |
| `projects` | `code` (`PRJ-0001`…), `name`, `client` (Faker company), `status` (`active`/`on_hold`/`closed`), `budget_cents`, `start_date`, `end_date` (nullable) |
| `tasks` | `project_id` FK, `name`, `budget_minutes` |
| `time_entries` | `user_id` FK, `project_id` FK, `task_id` FK (task must belong to project), `date_performed`, `minutes` (15-minute steps, 15–600), `billable` (0/1), `cost_rate_cents` (copied from the user at entry time), `notes` |
| `approvals` | `user_id` FK, `week_start` (a Monday), `status` (`submitted`/`approved`/`rejected`), `approver_id` FK nullable, `submitted_at`, `decided_at` nullable |

## Seed (`seed.py`)

- `build_db(path, seed=42)` drops and rebuilds. Same seed → byte-for-byte identical row content (Faker and
  `random.Random` both seeded; no wall-clock values: "now" is the fixed instant `2026-07-01T00:00:00Z`).
- Sizes: 40 users, 25 projects, 3–6 tasks per project, time entries for working days 2026-01-05 to and including
  2026-06-26 (about 5–6 entries per active user per day on 1–3 projects), one approval row per user per week.
- `created_at` of a time entry = its `date_performed` plus 0–3 days, at a random time; `updated_at` ≥ `created_at`;
  about 10 % of rows have `updated_at` later than `created_at`.
- Returns a dict of row counts per table.

## API (`app.py`)

All routes under `/v1`, all except `/v1/health` need `Authorization: Bearer <token>` (401 otherwise).

| Route | Behaviour |
|---|---|
| `GET /v1/health` | `{"status": "ok", "version": "0.1.0"}` |
| `GET /v1/{resource}` | resource ∈ users, projects, tasks, time_entries, approvals; unknown → 404. Envelope per ADR 0002. |
| `GET /v1/{resource}/{id}` | `{"results": [row], "meta": {"count": 1, ...}}`; missing → 404 |
| `PATCH /v1/projects/{id}` | body `{"version": int, ...fields}`; allowed fields `name`, `status`, `budget_cents`, `end_date`; others → 422. Stale version → 409 with body `{"error": "version_conflict", "current": row}`. Success sets `updated_at` to now (real clock), `version + 1`, returns the envelope. |
| `POST /v1/approvals/{id}/approve` and `/reject` | body `{"version": int, "approver_id": int}`; only from `submitted` (else 409 `invalid_transition`); sets `status`, `approver_id`, `decided_at`, bumps version. |

List filters (all optional, combined with AND; a filter that does not apply to the resource → 422):
`ids=1,2,3` · `created_between=YYYY-MM-DD:YYYY-MM-DD` · `updated_since=<ISO timestamp>` · `user_id` ·
`project_id` · `status` · `date_between=YYYY-MM-DD:YYYY-MM-DD` (time_entries.date_performed, approvals.week_start).
`order` per ADR 0002, default `id:asc`. `page` < 1 or `per_page` outside 1–200 → 422.

SQL safety: column and order names come from whitelists; values are always bound parameters.

Fault injection per ADR 0002: `chaos_rows` applies to `GET /v1/time_entries` list calls; `fault_rate` applies to
every `/v1` route except health; 429 carries header `Retry-After: 1`.

## CLI (`__main__.py`)

- `python -m ops_api seed [--db data/ops_api.db] [--seed 42]` → prints row counts.
- `python -m ops_api serve [--db ...] [--port 8000] [--chaos-rows 0] [--fault-rate 0]` → uvicorn. Token from env
  `OPS_API_TOKEN`; if unset, use `dev-token` and print a one-line warning that it is the demo token.

## Tests (must pass, `pytest -q`, plus `ruff check .` clean)

1. Seed determinism: two builds with seed 42 → same counts and same SHA-256 of all rows ordered by id; seed 7 differs.
2. Data integrity: every time entry's task belongs to its project; minutes are multiples of 15; every approval
   `week_start` is a Monday; all emails end in example.com/.org/.net.
3. Envelope and meta on every resource; `count` equals the table's row count with no filters.
4. Paging without changes: walking all pages of time_entries ordered `created_at:asc`, `per_page=200`, yields every
   id exactly once.
5. Filters: `created_between` and `date_between` inclusive on both ends; unknown filter for a resource → 422;
   `per_page=201` → 422.
6. Auth: no token and wrong token → 401; health needs none.
7. Get: existing id → one-row envelope; missing → 404.
8. PATCH: correct version → 200, version + 1, `updated_at` newer; stale version → 409 with `current`; disallowed
   field → 422.
9. Approvals: submitted → approved works; approving an approved row → 409 `invalid_transition`.
10. Chaos: with `chaos_rows=5`, a list call changes `updated_at`/`version` of 5 rows (seeded RNG → same 5 each run).
11. Faults: with `fault_rate=1.0`, a list call → 429 with `Retry-After`; health still 200.

## README

Add a "Run the mock API" section: create venv, `pip install -e ".[dev]"`, seed, serve, one `curl` example with
the bearer header, `pytest`.
