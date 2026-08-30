# SweaterCo Dispatch Desk - Week 4 Skeleton

This directory is a dependency-free Python skeleton for Track 2. It implements the
Week 4 contract and keeps language extraction separate from deterministic order,
eligibility, ETA, cost, and allocation tools.

## What works

- Three frozen dataclass contracts: `StructuredRequest`, `CandidateMetrics`, and
  `AllocationResult`.
- A deterministic Week 4 parser for the five canonical fixtures (replaceable by a
  structured-output LLM adapter later).
- Order resolution, workshop lookup, hard eligibility, ETA/cost calculations, and
  configurable allocation scoring.
- End-to-end golden paths: R09 `ALLOCATE`, R03 `CLARIFY`, R08 `REFUSE`, and R02
  `DECLINE`.
- Simulator baseline capture and an initial 30-request language ground truth.
- A zero-dependency mock UI showing the required request, recommendation,
  candidate comparison, warning, and audit/history regions.

## Run

From this `Workspace` directory:

```bash
python3 -m app.cli --request R09
python3 -m unittest discover -s tests -v
python3 evaluation/evaluate_simulator.py
python3 -m http.server 8000 --directory app/ui
```

Then open `http://localhost:8000` for the UI mock.

## Architecture

```text
chat -> parser -> order resolver -> conversation gate
                                  | READY
                                  v
                       eligibility -> ETA/cost -> allocator
                                                   |
                                                   v
                                         audit JSON / UI payload
```

The parser extracts only explicit language. It never calculates ETA, cost, defect
risk, queue state, or scores. Those values come from deterministic tools.

## Week 4 boundaries

This is intentionally a basic framework. The future LLM adapter, persistent queue
updates, live backend/UI binding, split batches, shock detection, and optimised
multi-objective policy remain planned work. See `KNOWN_ISSUES.md`.
