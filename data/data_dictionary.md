# Data Dictionary — Track 2 (The Quick-Response Subcontracting Desk)

Two small, clean CSV files plus the chat inbox. The CSVs have no missing values, no joins
to figure out, and no traps — every number can be taken at face value. The chat inbox is
deliberately *not* clean: it is the input your system must handle.

"Today" in the dataset is **2026-04-01**. Garments move through four stages:
**KNITTING → ASSEMBLY → WASHING → PACKING**.

| File | Rows | One row is |
|---|---|---|
| `orders.csv` | 120 | One customer order |
| `workshops.csv` | 8 | One outside workshop's profile card |
| `dispatch_requests.txt` | 30 | One allocation request, exactly as typed in the group chat |

## `orders.csv`

| Column | Meaning |
|---|---|
| `order_id` | `ORD-001` … |
| `customer`, `product` | Who ordered it and what it is |
| `category` | `TOPS` (sweaters, hoodies, …) or `ACCESSORIES` (beanies, scarves) |
| `pieces` | How many garments |
| `order_date`, `due_date` | When it was placed and when it is due |
| `status` | `COMPLETE` or `IN_PROGRESS` |
| `current_stage` | `KNITTING` / `ASSEMBLY` / `WASHING` / `PACKING` / `COMPLETE` |
| `last_activity_date` | The last day any work was recorded on this order |
| `completed_date` | When it finished (blank if still in progress) |
| `days_late` | `completed_date − due_date`; negative means early; blank if in progress |

## `workshops.csv`

The eight outside workshops that batches can be sent to. This file **is** the simulator's
model of each workshop — what you see is what you get. It answers the dispatcher's three
questions: *can they make it* (`makes`), *can they take it now* (`capacity_pieces_per_day`,
`current_queue_days`), and *are they allowed to* (`status`, `max_batch_pieces`).

| Column | Meaning |
|---|---|
| `workshop_id`, `name` | `W1` … `W8` and a memorable name |
| `capacity_pieces_per_day` | How much it can process per day; work beyond this queues |
| `pickup_lead_days` | Fixed transport overhead per batch |
| `defect_rate` | Chance a batch comes back defective and is partly redone |
| `cost_per_piece` | What it charges |
| `makes` | `TOPS`, `ACCESSORIES`, or `TOPS+ACCESSORIES` — what it is equipped for |
| `status` | `ACTIVE`, or `SUSPENDED` (failed a quality audit — may not take new work) |
| `max_batch_pieces` | Per-batch cap (workshops on trial); blank means no cap |
| `current_queue_days` | Days of work it is already holding "today" |
| `notes` | The one-line reputation a human dispatcher would give it |

## `dispatch_requests.txt`

Thirty allocation requests from the morning's group chat, one per line, written the way
people actually type: `R07 [08:23] Ravi: ORD-020 — 1200 vests. No special requirements,
just make Mar 31.` Some requests are complete; some carry constraints ("keep it away from
BudgetWorks"); some are ambiguous or missing a number and require a follow-up question;
some suggest a workshop that cannot take the job; a few cannot be answered from this data
at all. Your system's behaviour on every one of them is part of the Track 2 evaluation —
see the track description.
