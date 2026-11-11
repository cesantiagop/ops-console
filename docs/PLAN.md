# ops-console — build plan

A terminal admin console for a professional-services automation (PSA) system: browse projects and people,
review timesheets, and make **safe bulk changes** (preview → confirm → apply → audit log). It runs against a
**mock PSA API** with synthetic data, so anyone can clone it and run it in one command.

## Clean-room rules (read before every session)

1. **New code only.** Nothing is copied, translated or paraphrased from any employer's code, docs, tests or data.
   No employer file is opened while working on this repo.
2. **Synthetic data only.** All people, projects and numbers come from Faker with a fixed seed. No real names,
   emails, IDs, field numbers, URLs, rules or figures.
3. **Public knowledge only.** Patterns used here (pagination, idempotent writes, dry-run, audit logs, keyring)
   are general industry practice and are documented in the ADRs in my own words.
4. **Personal identity.** Commits use my personal GitHub email, not a work address.
5. **Check before push.** `gitleaks` + a search for employer names/domains runs before every push.

## What it demonstrates

| Skill | Where it shows |
|---|---|
| REST API client design | `client/`: session, retries with backoff, typed models, pagination |
| Data correctness under change | windowed pagination by `created_at` + de-duplication; a test that proves `updated_at` paging skips rows |
| Safe writes | changesets: CSV in → diff preview → confirm → apply → append-only ledger; dry-run is the default |
| Secrets handling | `keyring` with an env-var fallback; nothing in files or logs |
| Testing | pytest against the real mock API in-process; unit + integration; fixtures from the same seed |
| CI/CD | GitHub Actions: ruff + pytest on Python 3.11–3.13, gitleaks |
| Documentation | README with architecture diagram, ADRs for each design decision |

## Architecture

```
            +-------------------+        HTTP (JSON)        +----------------------+
  user ---> |  console (menus)  | ----> client (paging, ---> |  mock PSA API        |
            |  rich + prompts   |       retries, models)     |  FastAPI + SQLite    |
            +---------+---------+                            |  Faker seed data     |
                      |                                      +----------------------+
                      v
            changesets -> preview -> confirm -> apply -> ledger (SQLite, append-only)
```

## Mock API conventions (chosen, documented in ADR 0002)

- Envelope: `{"results": [...], "meta": {"count", "page", "per_page"}}`; max 200 per page.
- Money in integer cents, durations in integer minutes (no floats for money).
- Resources: `users`, `projects`, `tasks`, `time_entries`, `approvals`.
- Filters: `created_between`, `date_between`, `project_id`, `user_id`; ordering by `created_at` or `updated_at`.
- A "chaos" switch edits random rows during a long read, so the paging-drift test is real.

## Milestones

| # | Milestone | Done when |
|---|---|---|
| 0 | Repo skeleton, plan, license, .gitignore, first commit | pushed to GitHub |
| 1 | Mock API + seed data | `ops-api` serves all resources; tests pass |
| 2 | Client: models, retries, windowed pagination | drift test passes, `updated_at` test shows the skip |
| 3 | Console: read-only menus (search, hours by person/week, health check) | demo GIF in README |
| 4 | Changesets + ledger (dry-run default) | apply/undo round-trip test passes |
| 5 | CI: ruff, pytest matrix, gitleaks, badge | green badge on README |
| 6 | Polish: README story, ADRs, `make demo` / one-command run | a stranger can run it in 2 minutes |

## Later portfolio repos (same rules)

- `psa-lakehouse`: bronze → silver → gold on Postgres, Airflow/Dagster + dbt, ERD, data tests; reads `ops-api`.
- `psa-insights`: a Power BI (or open-source BI) report on the gold layer; screenshots + DAX + TMDL.
