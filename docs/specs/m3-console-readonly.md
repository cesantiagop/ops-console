# Spec — Milestone 3: console, read-only menus

Uses `ops_client` (M2). No writes in this milestone (M4 adds changesets).

## Layout

```
src/ops_console/
    __init__.py      # __version__ = "0.1.0"
    __main__.py      # `python -m ops_console [--base-url URL] [--demo]`; also script entry `ops-console`
    demo.py          # --demo: seed a temp db (seed 42), build the M1 app, wrap it in TestClient, return an OpsClient
    reports.py       # pure functions over models: no I/O, no rich
    views.py         # rich renderables built from report rows (tables, panels)
    menu.py          # the loop; `ask` (input function) and `console` (rich Console) are injected
tests/
    test_console_*.py
```

`pyproject.toml`: the lead adds `rich>=13` to dependencies and `[project.scripts] ops-console = "ops_console.__main__:main"`.

## `--demo` (the one-command experience)
`ops-console --demo` runs everything in-process: no server, no token setup. It seeds a temp SQLite file, creates the
M1 app with token `demo`, and gives the menu an `OpsClient(http=TestClient(app), token="demo")`. The temp file is
deleted on exit. A banner says it is synthetic demo data.

## Menu

```
ops-console — <base url or "demo (synthetic data)">
 1  Health check
 2  Search projects
 3  Project detail
 4  Hours by person by week
 5  Approvals waiting
 0  Exit
```

| # | Behaviour |
|---|---|
| 1 | API status and version; token source shown as `keyring`, `env` or `demo`, never the value; round-trip time in ms |
| 2 | Ask text (blank = all) and status (blank = any). Case-insensitive match on code, name or client. Table: code, name, client, status, budget ($). Max 50 rows shown, then "… N more". |
| 3 | Ask project code (`PRJ-0007`). Panel: name, client, status, dates, budget. Table of tasks: task, hours logged, budget hours, % used. Footer: total hours, labor cost ($), budget ($), remaining ($), % of budget used. |
| 4 | Ask start and end date (`YYYY-MM-DD`, end inclusive; blank end = start + 27 days). Read with `extract("time_entries", ...)` (ADR 0003). Table: person × ISO week (Monday start), hours with 1 decimal, row and column totals. Max 12 week columns, else ask for a shorter range. |
| 5 | Approvals with status `submitted`, oldest week first: person, week start, days waiting (from week end to today), count by week in a footer. |

Bad input (unknown code, bad date) → one red line and back to the menu; never a traceback. `OpsError` → one red
line with the error class and message. Ctrl+C or `0` → exit code 0.

## Money and hours (reports.py)
- Labor cost of an entry = `minutes * cost_rate_cents`, summed as integers, divided by 60 **once** at the end,
  rounded half-up to whole cents. Dollars only at display time (`$1,234.56`).
- Hours = minutes / 60, displayed with 1 decimal; totals are computed from minutes, not from rounded hours.
- Week = the Monday on or before `date_performed`.

## Tests
1. reports: cost sums are exact integer cents (a case where per-entry rounding would differ from sum-then-round).
2. reports: week bucketing (Sunday → previous Monday; Monday → itself); totals from minutes.
3. reports: % of budget used with a zero budget → shows "n/a", no ZeroDivisionError.
4. menu: scripted inputs `["2", "", "", "0"]` on the demo client → output has the projects table and "25" projects.
5. menu: `["3", "PRJ-0001", "0"]` → output has the panel and a tasks table; `["3", "NOPE", "0"]` → a red error line, no traceback.
6. menu: `["4", "2026-03-02", "2026-03-15", "0"]` → a table with 2 week columns and a grand total equal to the
   sum of minutes in the db for that range / 60.
7. menu: `["5", "0"]` → count equals the number of `submitted` approvals in the db.
8. menu: health shows token source and never the token value (search output for the token string).
9. `--demo` starts and exits with `["0"]`; the temp db file no longer exists afterwards.
10. An `OpsError` raised by the client inside an action → red line, menu continues.

Output is captured with `Console(record=True, width=120)`; tests assert on `console.export_text()`.
