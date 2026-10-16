# Running with uv, importing data, and managing accounts

## Start from a fresh download

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and open a terminal in the repository root (the folder containing `pyproject.toml`). These commands work in PowerShell, macOS and Linux shells:

```text
uv sync --locked
uv run --locked python -m app.setup
uv run --locked python -m app.server --backend offline
```

For Gemini parsing after setup, copy `.env.example` to `.env`, set `GEMINI_API_KEY`, then:

```text
uv run --locked --env-file .env python -m app.server --backend llm
```

Setup asks you to choose bundled or personal CSV files, set the queue snapshot date, confirm the import, and create your first account. Passwords are entered twice without echo. On success it prints offline and Gemini next-step commands. The application does not auto-load `.env`; deployments should inject keys into the process environment. Open <http://127.0.0.1:8000> and sign in. Account creation is a terminal operation; there is no web registration page.

The default database is `runtime/dispatch.sqlite3`. Existing users should stop the service, back up their database, run `uv sync --locked`, and start the server without running setup again. Setup never replaces an existing file, even an empty one. Use another `--db` path to try a different dataset.

The server and account CLI require an initialized database and no longer silently import sample data. The lower-level Database API and legacy demos/tests retain sample-seeding compatibility. Older databases still receive the existing migrations when opened; the database schema version remains 4.

## Bundled or personal data

The professor-provided files `data/orders.csv` and `data/workshops.csv` remain unchanged and are the format reference. To explicitly select them:

```text
uv run --locked python -m app.setup --sample --as-of 2026-04-01 --username dispatcher
```

For your own files, provide both paths. They may be outside the repository; quote paths containing spaces:

```text
uv run --locked python -m app.setup --orders "D:/private/orders.csv" --workshops "D:/private/workshops.csv" --db runtime/personal.sqlite3 --as-of 2026-10-09 --username professor
uv run --locked python -m app.server --db runtime/personal.sqlite3 --backend offline
```

Choose either `--sample` or both personal paths. `--yes` skips only the import confirmation, not password input. Setup validates the complete dataset before creating the database. Data and the first account are committed in one transaction; a failed initialization leaves no partial business data. Editing a CSV after import does not update the database.

Files must be UTF-8 CSV (UTF-8 BOM is accepted). Column names are case-sensitive. All required columns must contain values. Additional columns from the original CSV are accepted but unused by this application. Validation errors identify the file and row; duplicate IDs/names and non-finite numeric values are rejected.

| File | Required columns |
|---|---|
| Orders | order_id, customer, product, category, pieces, order_date, due_date, status |
| Workshops | workshop_id, name, capacity_pieces_per_day, pickup_lead_days, defect_rate, cost_per_piece, makes, status, current_queue_days |

Optional columns: `completed_date` for orders; `max_batch_pieces` and `notes` for workshops.

Current supported contract:

- Order IDs: `ORD-` plus exactly three digits, or `O` plus digits. Workshop IDs: `W` plus a positive integer without leading zeros. Use IDs in requests or the Edit details form for personal data; natural-language workshop-name aliases still use the original course vocabulary.
- Categories: `TOPS` or `ACCESSORIES`. Workshop `makes` joins capabilities with `+`. Customer, product and workshop names can contain Unicode. An order-ID-only request retrieves the product from your database.
- At most 8 workshops. This explicit limit keeps the current combination-based planner within its intended scale. Arbitrary IDs/categories, arbitrary column mappings and larger workshop sets are outside this change.
- Pieces and daily capacity are positive integers. Pickup lead days are non-negative integers. A blank maximum batch size means unlimited; otherwise it must be positive. Integer values are capped at 2^31−1.
- Defect rate is between 0 and 1. Cost and queue days are finite, non-negative numbers.
- Order status: `READY`, `IN_PROGRESS` or `COMPLETE`. As in the original course data, READY and IN_PROGRESS import as READY; COMPLETE imports as COMPLETED. **External production assignments, partial completions and audit history are not imported.** The import summary warns when IN_PROGRESS is converted.
- Workshop status: `ACTIVE`, `SUSPENDED` or `INACTIVE`; only ACTIVE is eligible.
- Dates use `YYYY-MM-DD`; due date cannot precede order date. A completed date requires COMPLETE status and cannot precede order date.

`--as-of` is the date on which the queue-day values were measured and the initial business date. The wizard suggests 2026-04-01 for sample data, or the local current date for personal files, and lets you change it. The server defaults to the latest queue snapshot date in its database; `--as-of` may advance but cannot rewind that date. Business time does not advance automatically each day. Legacy dispatch/session CLIs also need an explicit matching `--as-of` for personal data.

## Create and reset accounts

```text
uv run --locked python -m app.auth another_user --db runtime/personal.sqlite3
uv run --locked python -m app.auth another_user --reset-password --db runtime/personal.sqlite3
```

- Creation: `Account created successfully.`
- Duplicate: `Account already exists. Please sign in or use --reset-password.` The existing password and logins remain intact.
- Reset: `Password reset successfully. Existing logins have been revoked.`
- Resetting an unknown username fails rather than creating an account.

Usernames allow 1–64 letters, digits, dots, underscores or hyphens. Passwords require 12–256 characters. Use the same database path for setup, account commands and the server.

## Reproducible dependencies

`pyproject.toml` declares dependencies; `uv.lock` pins the resolved direct and transitive dependencies. Commit both files. `.python-version` selects Python 3.14.6; the supported project range is Python 3.11–3.14. uv can download the selected interpreter when unavailable locally. Initial installation requires network access and includes the Gemini SDK for complete testing. Offline application mode requires no model key, but first-time dependency installation still needs package access.

`--locked` rejects stale lockfiles rather than silently choosing new versions. Developers can intentionally update dependencies with `uv lock`, validate the change, and commit the updated lockfile. `requirements.txt` remains for legacy pip compatibility, not as the complete reproducible environment specification. The lockfile contains no passwords, CSV records, databases or API keys.

## Optional online models

Prefer process-environment injection (scalable for local and deploy). Locally, load a gitignored `.env` with uv:

```text
# Gemini
uv run --locked --env-file .env python -m app.server --backend llm

# DeepSeek (set DEEPSEEK_API_KEY in .env)
uv run --locked --env-file .env python -m app.server --backend deepseek
```

In PowerShell 7.1+, you can also set a key in the shell without placing it directly in command history:

```powershell
$env:DEEPSEEK_API_KEY = Read-Host "DeepSeek API key" -MaskInput
uv run --locked python -m app.server --db runtime/personal.sqlite3 --backend deepseek
```

Starting with `--backend llm` or `deepseek` without the matching key exits immediately with a short hint. The application does not automatically load `.env`. Restart after changing configuration; existing conversations retain their original backend. Personal files stay local, but online models receive request text for parsing; local storage does not imply fully offline processing.

## Verification

```text
uv run --locked python -X utf8 -m unittest discover -s tests -v
node --test tests/test_ui_state.cjs
```

`-X utf8` avoids conflicts between UTF-8 fixtures and older Windows default encodings. Python tests mock model calls. Frontend tests separately require Node 18+; the application does not need Node to start. Full acceptance commands are `uv run --locked python -X utf8 evaluation/verify_mvp.py` and `uv run --locked python -X utf8 evaluation/verify_ui.py`; these rewrite saved reports under `evaluation/results/`.
