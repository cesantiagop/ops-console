# Ledger sample: apply, undo, and an attempt to tamper

Captured from one `--demo` session on synthetic data (seed 42), 2026-11-11. The live ledger file
(`data/ledger.db`) is runtime state and is never committed; this page shows what it records.
Design: [ADR 0004](../adr/0004-safe-bulk-changes.md).

## 1. Apply `examples/projects_changes.csv`

The file asks for 3 rows; one is already at the desired value. The preview shows old → new before anything is
written, and applying required typing `APPLY 2`.

```
                  Planned changes
┌──────────┬──────────┬───────────────────────────┐
│ Code     │ Field    │ Old → New                 │
├──────────┼──────────┼───────────────────────────┤
│ PRJ-0001 │ status   │ active → on_hold          │
│ PRJ-0001 │ budget   │ $308,000.00 → $320,000.00 │
├──────────┼──────────┼───────────────────────────┤
│ PRJ-0004 │ end_date │ NULL → 2027-03-31         │
└──────────┴──────────┴───────────────────────────┘
              2 changes, 1 no_change
       Result
┌───────────┬──────┐
│ Outcome   │ Rows │
├───────────┼──────┤
│ applied   │    2 │
│ no_change │    1 │
└───────────┴──────┘
Run ID: 5171f5b1c52e444fa5682a7f61c799f9  (status done)
```

## 2. Undo that run

Undo is not a back door: it builds the inverse changeset from the ledger and goes through the same preview and
`APPLY <n>` confirmation.

```
                  Planned changes
┌──────────┬──────────┬───────────────────────────┐
│ Code     │ Field    │ Old → New                 │
├──────────┼──────────┼───────────────────────────┤
│ PRJ-0001 │ status   │ on_hold → active          │
│ PRJ-0001 │ budget   │ $320,000.00 → $308,000.00 │
├──────────┼──────────┼───────────────────────────┤
│ PRJ-0004 │ end_date │ 2027-03-31 → NULL         │
└──────────┴──────────┴───────────────────────────┘
              2 changes, 0 no_change
      Result
┌─────────┬──────┐
│ Outcome │ Rows │
├─────────┼──────┤
│ applied │    2 │
└─────────┴──────┘
Run ID: e39a0a8acc094f5a890688538a55c959  (status done)
```

## 3. The ledger afterwards

Every run: who, when, which file (SHA-256), and counts. The undo run points back to the run it reverses.

```
                                             Ledger: latest runs
┌─────────────┬────────────┬───────┬─────────────┬─────────┬─────────┬──────────┬───────┬───────────┬────────┐
│             │ Started    │       │             │         │         │          │       │           │        │
│ Run         │ (UTC)      │ Mode  │ Source      │ Changes │ Applied │ Conflict │ Error │ No change │ Status │
├─────────────┼────────────┼───────┼─────────────┼─────────┼─────────┼──────────┼───────┼───────────┼────────┤
│ e39a0a8acc… │ 2026-11-12 │ undo  │ undo:5171f… │       2 │       2 │        0 │     0 │         0 │ done   │
│             │ 00:40:52   │       │             │         │         │          │       │           │        │
│ 5171f5b1c5… │ 2026-11-12 │ apply │ projects_c… │       2 │       2 │        0 │     0 │         1 │ done   │
│             │ 00:40:52   │       │             │         │         │          │       │           │        │
└─────────────┴────────────┴───────┴─────────────┴─────────┴─────────┴──────────┴───────┴───────────┴────────┘
                                                    2 runs
```

Every field of every row, with the version the change was checked against (`1→2`):

```
                                Run 5171f5b1c52e444fa5682a7f61c799f9
┌──────────┬──────────┬─────────────┬─────────────┬─────┬───────────┬───────────────────────────────┐
│ Code     │ Field    │ Old         │ New         │ Ver │ Outcome   │ Message                       │
├──────────┼──────────┼─────────────┼─────────────┼─────┼───────────┼───────────────────────────────┤
│ PRJ-0003 │          │             │             │   1 │ no_change │ already at the desired values │
│ PRJ-0001 │ status   │ active      │ on_hold     │ 1→2 │ applied   │                               │
│ PRJ-0001 │ budget   │ $308,000.00 │ $320,000.00 │ 1→2 │ applied   │                               │
│ PRJ-0004 │ end_date │ NULL        │ 2027-03-31  │ 1→2 │ applied   │                               │
└──────────┴──────────┴─────────────┴─────────────┴─────┴───────────┴───────────────────────────────┘
                          apply · done · by demo-user · sha256 d80a4d9f941b
```

## 4. Trying to rewrite history

Straight SQL against the same ledger file. The database itself refuses, through triggers, so the guarantee does
not depend on the application behaving:

```
UPDATE run_rows SET new_value='0' WHERE id=1
  -> IntegrityError: ledger is append-only: run_rows cannot be updated
DELETE FROM run_rows WHERE id=1
  -> IntegrityError: ledger is append-only: run_rows cannot be deleted
DELETE FROM runs
  -> IntegrityError: ledger is append-only: runs cannot be deleted
```

(Someone with file access can still delete the whole file; in production the ledger would live in a database
where the application's role has INSERT-only rights, or be shipped to write-once storage.)
