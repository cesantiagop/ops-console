# Spec — Milestone 4: changesets + ledger

Decisions: [ADR 0004](../adr/0004-safe-bulk-changes.md). Builds on `ops_client` (M2) and `ops_console` (M3).

## Layout

```
src/ops_console/
    changeset.py   # parse + validate CSV -> list[Desired]; ChangesetError with every problem (line, column, message)
    plan.py        # build_plan(client, desired) -> Plan; Plan.changes / Plan.no_change; render via views
    ledger.py      # Ledger(path): SQLite, append-only (triggers), start_run / record / finish_run / runs / run_rows
    apply.py       # apply_plan(client, plan, ledger, run_id) -> Summary; inverse_changeset(ledger, run_id)
    menu.py        # add items 6, 7, 8 (below); M3 items unchanged
    __main__.py    # add subcommands: `changes plan FILE`, `changes apply FILE [--apply] [--yes]`, `ledger [RUN_ID]`, `undo RUN_ID [--apply]`
tests/test_changes_*.py
examples/projects_changes.csv   # a small valid example against the seed-42 demo data
```

## Changeset CSV (projects only in this milestone)
- Required column `code` (`PRJ-0001`). Optional columns: `name`, `status`, `budget_dollars`, `end_date`.
- Blank cell = no change. `end_date` value `NULL` = set to null.
- `budget_dollars`: plain number or with thousands commas (`12,500.00`), ≥ 0, max 2 decimals → cents via `Decimal`.
- `status` in active / on_hold / closed; `end_date` `YYYY-MM-DD`.
- Errors (all collected, then raised together): unknown column, missing `code`, duplicate `code`, unknown `code`
  (checked against the API), bad value. Line numbers are 1-based file lines (header = line 1).
- UTF-8 with or without BOM.

## Ledger (`data/ledger.db` by default, `--ledger PATH` to override)
- `runs(run_id TEXT PK, started_at, finished_at, mode, source_file, source_sha256, actor, n_changes, n_applied,
  n_conflict, n_error, n_no_change, status)` — `mode` ∈ dry_run / apply / undo; `status` ∈ running / done /
  cancelled / failed. `actor` = `getpass.getuser()`.
- `run_rows(id INTEGER PK, run_id FK, ts, resource, row_id, row_key, field, old_value, new_value,
  version_before, version_after, outcome, message)`; values stored as JSON text.
- Triggers: any UPDATE or DELETE on `run_rows` raises. On `runs`, only `finished_at`, the counters and `status`
  may change, and only while `status = 'running'`.
- `run_id` = UUID4 hex.

## Flow
plan → preview table (key, field, old → new; money shown in dollars) → counts (changes, no_change) →
confirm prompt `Type APPLY <n> to apply, anything else cancels` → apply → summary table by outcome → run_id shown.
Dry-run (`changes plan`, or `changes apply` without `--apply`) records outcome `dry_run` per change and status
`done`, writes nothing to the API. `--yes` skips the prompt only together with `--apply`.

## Menu additions
- `6  Bulk change projects (CSV)`: ask path → plan → preview → confirm → apply.
- `7  Ledger`: last 10 runs; ask a run_id (blank = back) → its rows.
- `8  Undo a run`: ask run_id → inverse changeset → same preview/confirm path; ledger `mode = undo`,
  `source_file = "undo:<run_id>"`.

## Tests
1. Parse: valid file → desired values; dollars `12,500.50` → 1250050 cents; `1.005` → error; BOM handled.
2. Validate: a file with 3 different errors raises once, listing all 3 with line numbers; nothing applied.
3. Plan: a row already at the desired value → `no_change`; changes carry the read version.
4. Dry-run: API unchanged; ledger run `mode=dry_run`, rows `dry_run`.
5. Confirm: wrong text → nothing applied, run `status=cancelled`.
6. Apply: values changed in the API; ledger rows `applied` with version_before/after; summary counts right.
7. Conflict: change one target row through the client between plan and apply → that row `conflict`, the rest
   `applied`; run `status=done`.
8. Ledger is append-only: UPDATE and DELETE on `run_rows` raise; editing a finished run raises.
9. Undo round trip: apply then undo → every touched field back to its original value; undo run linked by
   `source_file = "undo:<run_id>"`.
10. Menu: `["6", "<path>", "APPLY 2", "7", "", "0"]` in demo mode works end to end.
11. CLI: `changes plan examples/projects_changes.csv --demo` exits 0 and prints the preview.
