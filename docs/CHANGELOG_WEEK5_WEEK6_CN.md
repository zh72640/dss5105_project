# Week 5/6 file changelog

Historical date: 2026-09-14. The inventory was built from before/after SHA-256 comparisons within the original workspace: **50 files added, 10 modified, 0 deleted**. It did not rely on a parent Git repository. This was the first production-data parser and allocation implementation, before lifecycle, sessions, authentication, jobs, and dynamic Agent chat. The separate [Gemini changelog](CHANGELOG_GEMINI_CN.md) records the official SDK adaptation requested afterward.

## Added source and evidence

| Area | Historical additions |
| --- | --- |
| Parser | Frozen `README_parser.md` and ParseResult schema; legacy fixture parser for explicit compatibility; normalization lexicon, rule parser, validator, and the then-current Gemini client. The validator checked JSON/schema, domain constraints, and evidence from the input rather than filling missing values. |
| Allocation | Deterministic single-workshop and integer split planner with workshop limit, objective, and hard-deadline filtering. |
| Database | SQLite package, versioned `001_initial.sql`, CSV import, order and workshop repositories, current queue lookup, transactions, and the orders/workshops/queue/request/parsing/working/unassigned/completed/lapsed/decision tables. |
| Server and demos | Local JSON HTTP server; real retrieval trace, five mock backend cases, and a Week 6 isolated-database allocation/replay demonstration. |
| Evaluation | Original 30-request behavior regression, parser field metrics and invention checks, explicit live Gemini smoke/full-run command, one-command MVP verification, offline per-case JSONL, dispatch traces, test output and summary, and official baseline checks. |
| Tests and fixtures | Sixty fully specified parser golden cases (46 edges), integer brute-force comparisons, twenty numbered end-to-end scenarios plus error/concurrency cases, SDK mock-HTTP tests, parser transport tests, and real HTTP tests. |
| Documents and configuration | `.env.example`, `.gitignore`, Gemini/system/database/next-stage/acceptance guides, source hash manifests, locked direct SDK requirement, and a placeholder runtime directory. |

The ten historically modified files included the old README and known-issues files, main parser/prompt/CLI/pipeline/UI, Week 4 schema-contract documentation, and golden/tool tests. The parser stopped selecting hard-coded output by R-number; it gained offline/LLM parsing, schema and evidence validation, and one retry. The pipeline used registered database facts and a write transaction with state protection, idempotency, and a trace. The page replaced an R09 mock with real submission and history. Tests fixed the offline backend explicitly so an environment variable could not accidentally call a paid model.

The original Week 4 plans, source CSV and dictionaries, official simulator harness, baseline results, language ground truth, historical fixtures, and older schemas/tools remained intact. No existing persistent business database was reset; tests and browser demonstrations used memory or isolated temporary databases.

At that stage, the full local tests, 60-case offline parser set, 30-request behavior regression, and simulator baseline consistency were recorded in `evaluation/results/verification_summary.json`. The page had submitted a real test allocation. Live Gemini acceptance still required a configured key; the source Data Schema2 definition and a second independent label review were missing.

The source inventory excluded regenerable `__pycache__`, system metadata, virtual environments, runtime databases, approved temporary PDF-reading tools, and temporary screenshots/scripts. The old `file_change_manifest.json` stores machine-readable hashes and does not hash itself. File paths in this historical inventory have since been reorganized into current `app/agent`, `app/services`, and `app/tools` packages.
