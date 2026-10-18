# Offline test workflow

Run from the repository root. The workflow uses temporary databases and scripted model transports. It does not call real DeepSeek/Gemini services or change the default application database. Each run creates a new directory under `evaluation/live_results/`; historical checked-in evidence stays unchanged.

## Run all checks

The project needs its locked Python environment, Node 18+ and local Chrome/Chromium. Browser acceptance also needs Playwright. With the existing project environment, uv can provide Playwright in a separate environment without editing `pyproject.toml` or `uv.lock`:

```bash
uv sync --locked
uv run --no-project --python .venv/bin/python --with playwright python evaluation/run_test_workflow.py
```

The first command is environment setup, not required again if dependencies are already installed. The second may download Playwright if it is not cached; it does not download a browser. On macOS the workflow defaults to installed Google Chrome. On Linux it searches for `chromium` or `google-chrome`. For another installation, append `--browser-executable /path/to/chrome`.

If Playwright is already installed in a separate Python environment:

```bash
.venv/bin/python evaluation/run_test_workflow.py --browser-python /path/to/playwright/python
```

For a focused rerun, select stages explicitly:

```bash
.venv/bin/python evaluation/run_test_workflow.py --stages python frontend language http
```

Unselected stages remain `NOT_RUN`, and the result is `PARTIAL`, not full acceptance. Each stage has a default 300-second timeout. Use `--timeout-seconds` to change it. `--output-dir` must name a new directory; the runner refuses to overwrite an existing one.

## Stages and acceptance criteria

| Stage | What it checks | Gate |
| --- | --- | --- |
| Python | Allocator, hybrid split optimum on small exhaustive cases, alternatives, constraints, owner/auth boundaries, transactions, lifecycle, mocks, replay and recovery | All discovered tests pass; zero discovered tests fails |
| Frontend | Chat controller, confirmation state, candidate cards, alternatives, review changes and dashboard chart helpers | All Node tests pass; zero discovered tests fails |
| Native Agent | Real LangGraph/Tool/Service path with scripted model replies; revise, approve, replay, production event and saved question resume | Acceptance assertions pass; confirmation and production happen exactly once |
| Offline language | Original 30 development requests, one temporary database per case | All 30 service responses succeed; no production writes; new behavior mismatches fail |
| HTTP | Real loopback server, account login, previews, confirmations and authenticated audit exports | 20 previews, 10 confirmations, 10 matching audit records; observed local responses below 3 seconds |
| Simulator | Seven policies under standard and shock scenarios, seed 5105 | 14 complete runs of 120 orders; metrics equal the checked-in scope-review baseline |
| Browser | Actual headless Chrome interactions, fresh profile and database | Four allocation scenarios and five dashboard/tracking scenarios pass; no page errors; screenshots saved |

The historical language labels for R02 and R13 expect `DECLINE`; current Chat v2 returns `CLARIFY`. These exact differences produce warnings and remain visible, including the 28/30 match count. Labels are not rewritten. Any different mismatch fails the workflow. This dataset is not an independent holdout, and explanation faithfulness is not scored.

The simulator uses a single-workshop adapter; its passing metrics do not validate split improvements. The Python exhaustive tests cover the current-order split objective. The local HTTP timing gate is a regression check, not a live-model response-time guarantee or a concurrency benchmark.

## Manual presentation rehearsal

Use a **new, separate** demo database. Choose a new filename if this one already contains your earlier rehearsal data; do not delete or reuse the production database to reset a demo.

```bash
.venv/bin/python -m app.cli.setup --sample --db runtime/test-rehearsal.sqlite3 --as-of 2026-04-01 --username rehearsal --yes
.venv/bin/python -m app.server --backend offline --db runtime/test-rehearsal.sqlite3 --as-of 2026-04-01 --port 8018 --no-auth
```

Setup asks for a password and refuses to replace an existing database. Run setup once for each fresh rehearsal database; the server requires an initialized database even in `--no-auth` mode.

Open <http://127.0.0.1:8018/chat>, keep Offline mode, and use a new chat for each independent scenario. `--no-auth` is for this local rehearsal only. Confirmation changes the rehearsal database.

| Step | Action | Expected result |
| --- | --- | --- |
| 1 | Send `Allocate ORD-045 to OldMill; exclude W3.` | Conditional options appear; requirements remain unchanged; no confirmation button or allocation commit |
| 2 | In a new chat A, send `Allocate ORD-045 fastest.` | On the fresh bundled snapshot, W6 is recommended; do not confirm yet |
| 3 | In another chat B, send `Allocate ORD-096 fastest.` and confirm | B commits once and consumes capacity |
| 4 | Return to A and confirm the old card | No commit; a new W8 recommendation and before/after differences require review |
| 5 | Refresh A, expand the changes, then confirm the new card | Differences persist after refresh; new plan commits; the Committed button becomes disabled |
| 6 | In a new chat, send `Allocate ORD-055 fastest using at most two workshops.` | Expand Compare complete candidate plans; inspect workshop quantities, delivery, cost and quality |
| 7 | View the alternatives page at 390px width | No horizontal page overflow; alternatives remain readable |

These exact W6/W8 expectations use the bundled fresh data and its 2026-04-01 business date. Earlier confirmations or another dataset can change the recommendation. Automated browser acceptance recreates its own fresh database every time.

For the operations dashboard, open <http://127.0.0.1:8018/>. Hover or focus chart bars and the availability legend to inspect values. Search for an order and select it to open its journey. Confirm a production update through the existing form, then reload the order URL and verify the recorded quantities and event remain. Imported completed orders explicitly mark missing intermediate milestones. See the [dashboard guide](OPERATIONS_DASHBOARD.md) for data definitions. Automated dashboard acceptance uses its own temporary records to cover cancellation, reallocation, reassignment, completion and a 390px mobile viewport.

## Read the evidence

The terminal prints the run directory and each stage result as it completes. `report.md` is the readable report, `summary.json` is the machine-readable result, and `source-manifest.json` records source hashes. Each stage retains its log. Browser screenshots, detailed language responses, simulator outcomes and Agent traces stay in the same directory.

`PASS_WITH_WARNINGS` means required checks completed with visible qualifications. `FAIL` and `INTERRUPTED` return a nonzero exit code. `PARTIAL` means only selected stages ran. Missing browser dependencies are a failed requested stage, not a silent skip. A change to source files during execution invalidates the overall run. Real provider acceptance is always `NOT_RUN` in this workflow.
