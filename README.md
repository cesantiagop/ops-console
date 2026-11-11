# ops-console

A terminal admin console for a professional-services automation (PSA) system, built to show how to read and
change business data **safely**: windowed pagination that doesn't skip rows, bulk changes that are previewed,
confirmed and logged, and secrets that never touch a file.

> Work in progress. Runs against a bundled **mock API with synthetic data**: no real system, people or numbers.

## Run the mock API

Needs Python 3.11 or newer. All data is synthetic (Faker, seed 42).

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

python -m ops_api seed --db data/ops_api.db     # builds the synthetic database, prints row counts
python -m ops_api serve --db data/ops_api.db    # http://127.0.0.1:8000, token from OPS_API_TOKEN
```

If `OPS_API_TOKEN` is not set, the server uses the demo token `dev-token` and prints a warning. Try it
from a second terminal:

```powershell
curl.exe -H "Authorization: Bearer dev-token" "http://127.0.0.1:8000/v1/projects?per_page=2"
```

(`curl.exe`, not `curl`: in Windows PowerShell `curl` is an alias for `Invoke-WebRequest`. On macOS/Linux use
`curl`. Or open http://127.0.0.1:8000/docs for the interactive API docs.)

Fault injection is off by default: `--chaos-rows 5` edits 5 random time entries on every time-entry list
call (rows that change while you page), `--fault-rate 0.2` answers 20 % of requests with 429. The
conventions are in [ADR 0002](docs/adr/0002-mock-api-conventions.md).

Tests and lint:

```powershell
pytest
ruff check .
```

## Status

See [docs/PLAN.md](docs/PLAN.md) for milestones and the design.

## License

MIT, see [LICENSE](LICENSE).
