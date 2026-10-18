# Local workspace consolidation — 2026-10-18

The original `Workspace` is now the active application checkout on `ningtao`. Its Git history was fast-forwarded from `6e269de` to the published `4925cfa`. No merge commit, history rewrite or new push was needed. The remote tracking branch was refreshed and matches the local commit.

The seven uncommitted workflow files from `remote-checkouts/dss5105_project-20261017` were copied into this checkout: `README.md`, `evaluation/verify_dynamic_agent.py`, `evaluation/verify_ui.py`, `evaluation/run_test_workflow.py`, `tests/test_test_workflow.py`, `docs/TEST_WORKFLOW.md` and `docs/TEST_RUN_2026-10-18.md`. The two previous local evidence directories were also copied so their report links remain valid. These workflow changes remain uncommitted.

## Preserved files and recovery

- The original `docs/SPRINT1_QA_PREP_CN_EN.md`, `runtime/dispatch.sqlite3` and `runtime/preview-v03.sqlite3` retained their pre-merge SHA-256 hashes. The original databases were not opened by the new application or migrated.
- `runtime/local-merge-backup-20261018T063328Z/original-project.tar.gz` contains the original project files and the protected local files. Its `manifest.json` records provenance, preserved hashes and copied paths.
- The original Python environment is preserved in that backup directory as `venv-before-merge`. A new Python 3.14.6 environment was built from `uv.lock` using cached dependencies; the lockfile is unchanged.
- The independent clone is retained. Its incomplete AOCI index and machine-specific integration files remain there; the active checkout uses the committed project instructions and ignore rules.

## Verification in the original directory

The [complete workflow report](../evaluation/live_results/workflow-20261018T063428099743Z/report.md) records `PASS_WITH_WARNINGS` across all seven stages. It includes 287 passing Python tests, 47 passing frontend tests, mocked native Agent acceptance, authenticated HTTP and audit checks, 14 simulator configurations and browser acceptance. The tested source remained unchanged during the run.

The visible qualifications remain unclosed test-resource warnings and the R02/R13 historical language-label differences: 30/30 successful Offline responses, 28/30 historical labels matched. Real model acceptance was not run. The logs and screenshots are local ignored evidence, not a new published archive.

## Continue from this directory

The existing rehearsal database was copied with SQLite's backup API and passed an integrity check. Its saved chat-session count was verified. The old 8018 rehearsal process was stopped, and the service was restarted from the original `Workspace` with the copied database:

```bash
.venv/bin/python -m app.server --backend offline --db runtime/test-rehearsal-20261018-1023.sqlite3 --as-of 2026-04-01 --port 8018 --no-auth
```

The service is available at <http://127.0.0.1:8018/chat>. It uses an isolated rehearsal database and Offline mode. The separate 8017 service in the retained clone was left running.

Use [TEST_WORKFLOW.md](TEST_WORKFLOW.md) for repeatable automation and manual rehearsal steps. Future work should use this original checkout; the retained clone is available for comparison and recovery.
