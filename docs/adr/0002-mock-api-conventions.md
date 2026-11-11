# ADR 0002: Mock PSA API conventions

**Status:** accepted · 2026-11-11

## Context
The console needs a realistic API to run against: one that has the problems real APIs have (paging limits,
rows that change while you read them, rate limits, two people editing the same record). It must also run
anywhere with no account, so it is a local mock with synthetic data.

## Decision
- **Envelope.** Every list and every single-item read returns `{"results": [...], "meta": {...}}`. Clients always
  iterate `results`; a single item is a one-element list. One shape means one parser.
- **Paging.** `page` (1-based) and `per_page` (default 50, max 200; more is a 422, not a silent cap). `meta`
  carries `count` (all matching rows), `page`, `per_page`, `page_count`.
- **Units.** Money is integer **cents**, durations are integer **minutes**. No floats for money: sums stay exact.
- **Time.** Timestamps are ISO 8601 UTC with `Z`; calendar dates are `YYYY-MM-DD`. Date ranges are inclusive on
  both ends.
- **Ordering.** `order=<field>:<asc|desc>` on `id`, `created_at` or `updated_at`, always with `id` as tie-breaker
  so paging is deterministic.
- **Optimistic concurrency.** Every row has a `version`. A write must send the version it read; a stale version
  gets **409 Conflict** and the current row. Last-writer-wins is never silent.
- **Auth.** `Authorization: Bearer <token>`; missing or wrong token is 401. The token is configuration, never code.
- **Fault injection (off by default).** `chaos_rows`: each list read of time entries first edits N random rows
  (new `updated_at`, `version + 1`), which reproduces "rows change while you page". `fault_rate`: that fraction of
  requests gets **429** with `Retry-After`. Both use a seeded RNG so tests are repeatable.

## Consequences
The client (milestone 2) must handle paging drift, 429 back-off and 409 conflicts for real, and the tests can
prove it. The conventions resemble common PSA/REST APIs without copying any one vendor's API.
