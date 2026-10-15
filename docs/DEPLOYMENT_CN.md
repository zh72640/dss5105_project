# Deployment, upgrade, and recovery

This guide keeps its historical filename for existing links. The current local MVP uses FastAPI, Uvicorn, LangGraph, and SQLite schema version 9. It is intended for a single local server process bound to `127.0.0.1`; public hosting, tenant isolation, and HTTPS termination are outside this setup.

## First run

From the repository root:

```bash
uv sync --locked
uv run --locked python -m app.cli.setup
uv run --locked python -m app.server --backend offline
```

Open <http://127.0.0.1:8000> and sign in with the regular account created by setup. The interactive setup can import the bundled 120 orders and eight workshops or your own CSV files. It refuses to overwrite an existing database. The default database is `runtime/dispatch.sqlite3`; later startups do not reimport CSV data. See [Setup and data import](UV_SETUP.md) for CSV fields, account setup, and platform-specific commands.

For a separate database, give the same `--db` path to setup, account commands, and the server. The business date controls queue aging and estimates, while audit timestamps use actual UTC time. Stop the server before backup or maintenance.

## Models and credentials

Offline mode runs the separate rules demonstration. LLM chat uses native model tool calls and requires a configured provider. Set provider credentials in a local environment file or the process environment, then start with the explicit environment file option when needed:

```bash
uv run --locked --env-file .env python -m app.server --backend llm
```

The app does not load `.env` automatically. OpenAI, Claude, Gemini, and DeepSeek integrations are configured at startup. A model that cannot provide native tool calls returns `TOOLS_UNSUPPORTED`; the system does not parse a JSON-looking plan as tool calls. Local schema-binding tests do not prove the provider account has working network access or sufficient quota.

## Accounts and access

Setup creates a regular user. To add another regular user, use `uv run --locked python -m app.cli.auth USERNAME`; to reset its password, add `--reset-password`. Use `--db` for a nondefault database. Repeat registration does not replace an existing password. A built-in administrator is provisioned with a reserved username and a maintainer-supplied password; ordinary account commands cannot create or reset it. Upgrading an older database with a conflicting `admin` username aborts and rolls back.

Business APIs require an authenticated account by default. Users share one local business workspace, while API operations retain owner and role checks where applicable. `--no-auth` is an explicit local demonstration mode using `local-demo`; it is not a named human approver.

## Backup before upgrade

Do not rerun setup on an existing database. Stop all writers and create a consistent SQLite backup. This example uses the default database:

```python
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

source_path = Path("runtime/dispatch.sqlite3")
backup_dir = Path("runtime/backups")
backup_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
backup_path = backup_dir / f"dispatch-{stamp}.sqlite3"
with closing(sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)) as source:
    with closing(sqlite3.connect(backup_path)) as target:
        source.backup(target)
        assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
print(backup_path)
```

Backups include business data, account password hashes, login token hashes, Agent run traces, and LangGraph checkpoints. Store them privately and do not commit them to Git. After a code update and dependency sync, starting the application applies missing migrations transactionally. Unknown future schema versions are refused. Schema version 9 adds durable Agent run, tool-call, and event tables; it does not replace the established production tables.

## Restore and restart behavior

To restore, stop the server, keep the current database separately, copy a trusted backup to a new path, and start the app with `--db` pointing to that copy. Verify `/api/health`, sign in, inspect an order and recommendation, and check SQLite `PRAGMA integrity_check` and `PRAGMA foreign_key_check`. Consider resetting account passwords after restoring an old backup to revoke copied login sessions.

An interrupted LLM chat turn is resumed with the same session and request ID. LangGraph restores execution position from SQLite, but a node may run again. Tool invocation keys and lifecycle event IDs make side effects idempotent. Do not submit a new request ID merely because a response was lost; first retry the original request and inspect the owner-scoped trace at `GET /api/chat/sessions/{session_id}/trace`. Recovery never grants user confirmation. Explicit confirmation must still name the saved recommendation and expected session version.

## Verification and troubleshooting

```bash
uv run --no-sync python -X utf8 -m unittest discover -s tests -p 'test_*.py' -q
node tests/test_chat_ui.cjs
node tests/test_ui_state.cjs
```

Tests use temporary databases and mocked model transports. They do not establish live model quality. A version conflict requires refreshing the current order or session, not guessing a later version. If a request outcome is uncertain, retry with its original idempotency key. If the page shows old assets after an update, restart the server and refresh the browser. See [Known limits](../KNOWN_ISSUES.md) and the [Agent architecture](AGENT_SKILL_ARCHITECTURE.md) for current operational boundaries.
