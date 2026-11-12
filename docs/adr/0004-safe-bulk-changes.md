# ADR 0004: Safe bulk changes (changeset → preview → confirm → apply → ledger)

**Status:** accepted · 2026-11-11

## Context
Bulk edits are where admin tools do the most damage: a spreadsheet with one wrong column, a stale copy of the
data, a run that dies halfway. The usual failure is not a crash, it is a silent wrong write that nobody can
explain a month later.

## Decision
1. **Changesets are files.** A CSV keyed by a human key (`code`), one column per field. Blank cell = leave as is.
   The file is hashed (SHA-256) so the ledger can say exactly which file was applied.
2. **Validate everything before anything.** Unknown keys, duplicate keys, bad values or unknown columns stop the
   whole run with every problem listed by line number. Nothing is applied from a file that has any error.
3. **Plan against live data.** Read each target row now; compare current vs desired per field. Rows already at the
   desired value become `no_change`. The plan keeps the `version` it read.
4. **Preview, then an explicit confirm.** The plan is shown as a table (row, field, old → new). Applying requires
   typing `APPLY <n>` where n is the number of changes. Anything else cancels. **Dry-run is the default**: the CLI
   only writes with `--apply`.
5. **Apply row by row with the planned version.** A 409 means someone changed the row after the plan: record a
   `conflict`, do not retry, continue with the other rows, and report it. No silent last-writer-wins.
6. **Append-only ledger.** Every run and every row outcome (`applied`, `no_change`, `conflict`, `error`,
   `dry_run`, `cancelled`) is written to a local SQLite ledger whose triggers reject UPDATE and DELETE.
7. **Undo is a changeset too.** `undo <run_id>` builds the inverse of the run's `applied` rows (old values) and
   sends it through the same validate → plan → preview → confirm path. Undo is never a back door.
8. **Money in files is dollars, in the API cents.** Converted with `Decimal`, more than 2 decimals is an error,
   never rounded.

## Consequences
More steps than "loop and PATCH", but every write is explainable: who, when, which file (hash), old → new, and
what happened. Conflicts surface instead of overwriting a colleague's edit.
