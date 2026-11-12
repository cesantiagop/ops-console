# ADR 0003: Reading data that changes while you read it

**Status:** accepted · 2026-11-11

## Context
Offset paging (`page=1, 2, 3…`) is only correct if the ordering of rows does not change between page requests.
Ordering by `updated_at` breaks that: when a row on an already-read page is edited, it jumps to the end, every
row after it slides up one position, and the first row of the next page slides onto the page you already read.
That row is **silently skipped**. On a busy system a long extract loses rows and nothing errors.

## Decision
1. **Full extracts page inside `created_at` windows**, ordered `created_at:asc` (with `id` tie-break). A row's
   `created_at` never changes, so edits cannot move rows between pages. Windows (default 7 days,
   `created_between`, inclusive) keep each paged result small.
2. **De-duplicate by `id`**, keeping the row with the highest `version`.
3. **Check each window**: the number of unique ids read must equal `meta.count` from the window's first page.
   On a mismatch, read the window again (up to 3 times), then raise `IncompleteWindowError`. A wrong total is an
   error, never a warning.
4. **Retries**: 429 waits for `Retry-After` (capped at 30 s); 5xx and connection errors use exponential back-off
   with jitter; max 5 retries. Other 4xx are not retried: they are bugs or decisions.
5. **409 is never retried automatically.** The caller gets a `ConflictError` holding the current row and decides.
6. **Token**: keyring first (`ops-console` / `api_token`), then env `OPS_API_TOKEN`. Never printed, logged or
   included in `repr`.

## Consequences
The test suite includes a test that *demonstrates* the skip with naive `updated_at` paging under the mock's chaos
switch, next to a test proving the windowed reader returns every id. The cost is more requests (one or more per
window), which is the right trade for correctness.
