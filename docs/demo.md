# Reset a local demo

The reset replaces **one explicitly named database** with the bundled 120 orders,
8 workshops and April 1, 2026 business date. It preserves account names, roles and
password hashes, clears conversations/recommendations/production activity, and
requires everyone to sign in again. It never runs automatically at startup.

1. Stop every server or script using that demo database (Ctrl+C in its terminal).
2. Run from the repository root, replacing the example path with your actual demo:

   ```sh
   uv run --locked python -m app.cli.reset_demo --db runtime/demo.sqlite3 --server-stopped
   ```

3. Keep the printed backup path. The complete pre-reset database is stored under
   `runtime/backups/<database>-<timestamp>/before-reset.sqlite3` for this example.
   Backups contain private account and conversation data and must stay local.
4. Start the same database and sign in using the same credentials:

   ```sh
   uv run --locked python -m app.server --db runtime/demo.sqlite3 --backend deepseek
   ```

The process must inherit `DEEPSEEK_API_KEY`; use `--backend offline` for a rules-only
demo. The reset command does not load keys or change passwords. It requires an
existing database and has no default target. `--server-stopped` is an operator
confirmation; SQLite busy/sidecar checks cannot prove that all unrelated processes
have exited. Do not pass the flag while a server is running.

To restore: stop every process using the database, then copy the reported backup
to a **new filename**, for example `runtime/restored-demo.sqlite3`, and start the
server with that path. Keep the reset copy until restoration is verified.

# Development environment

Use a stable installed Python interpreter with `uv sync --locked`. If a virtual
environment points to a deleted temporary interpreter, stop the server and recreate
its interpreter binding with `uv venv --allow-existing --python /absolute/path/to/python .venv`,
then run `uv sync --locked`. This preserves files before uv reconciles dependencies.


# Optional browser acceptance

Python and Node unit tests do not require a browser. The extra acceptance script
requires `@playwright/test` and its Chromium installation. Install it outside tracked
source (for example `runtime/browser-check`), then run:

```sh
npm install --prefix runtime/browser-check @playwright/test
runtime/browser-check/node_modules/.bin/playwright install chromium
PLAYWRIGHT_MODULE="$PWD/runtime/browser-check/node_modules/@playwright/test" \
  node evaluation/verify_chat_feedback_browser.cjs
```

Set `CHROME_EXECUTABLE` to use an existing Chrome installation, or omit it for
Playwright's bundled Chromium. The script starts a temporary server/database and
does not reset the current demo.
