# UI requirement integration

The desk now uses the visual design in `../UI_requirement/ui/ui/` and the interactions described in `UI_QA_Checklist_v1021.xlsx`. These paths are relative to the project directory above this repository. The application continues to use authenticated server data and Chat v2.

## Pages

- **Login:** striped knit illustration, stitched brand label, account form, password visibility and accessible error feedback. Both `/` and `/chat` use the same design. No prototype credentials were introduced.
- **Dashboard:** top navigation, five KPI cells, pending conversations ordered by creation time, workshop availability, overdue orders and order status. Average waiting time uses actual request creation timestamps. Due-date comparisons use the business date. The dashboard's New request button was removed as required by D005; new requests begin in Requests.
- **Requests:** FIFO conversation list, central conversation, persistent requirements and recommendation panel, colored allocation quantities, candidate comparison, explicit confirmation, rejection/revision, marking a request not allocated, and a recorded decision timeline. Completed and archived conversations remain accessible.
- **Orders:** search, status switches, sortable columns, the oldest 20 matching non-completed orders, Show all, expandable completed orders, actual decision notes and `decision_logs.txt` downloads. Clicking an order opens existing production tracking and controls.
- **Workshops:** capacity and queue summary, status and capability filters, consistent knit colorways, registered costs and defect rates, and a production queue dialog. Split assignments are identified when an order has multiple active workshop assignments.
- **History and recommendations:** existing audit exports, recommendation confirmation and production actions remain available. The previous interactive analytics are under **Workshop analytics & order progress**.
- **Responsive layout:** top tabs scroll on narrow screens, wide tables scroll within their panels, the request list becomes a mobile menu, and the full review panel follows the conversation. Text-size preferences are retained.

## Integration decisions

The reference files are a local-storage prototype. Its mock records, authentication, client-side allocation and destructive Reset demo action were not copied. Resetting the business database remains outside this UI update.

The current backend checks extracted requirements and prepares recommendations in the same turn. The UI displays those checked fields and keeps the existing explicit allocation confirmation; it does not add a new extraction-confirmation API or restore retired v1 endpoints.

**Mark not allocated** archives the request using the existing guarded Chat v2 action. It does not lapse or reject the underlying order. Consequently the order register uses the existing **Lapsed** production state, while rejected and cancelled requests appear in the conversation record. Delayed orders form a separate filter group and still display their recorded production state.

Workshop queues contain active named assignments plus potentially anonymous imported workload. The dialog labels named jobs by registered order date. It does not invent FIFO scheduling positions, actual start dates or completion dates that the current API does not provide. Estimated next availability uses the business date plus the rounded-up current queue duration.

No allocation algorithms, transaction policies or database schemas changed. The session-list read model adds creation time, task state and order ID for the FIFO interface, while retaining account ownership and cursor pagination. Local SVG textures comply with the existing content security policy.

## Changed components

| Area | Files |
| --- | --- |
| Shared visual system | `app/ui/design-system.css`, `design-system.js`, `knit.svg`, `knit-large.svg` |
| Desk pages | `app/ui/index.html`, `desk.js`, `desk-views.js` |
| Requests and plan cards | `app/ui/chat.html`, `chat.css`, `chat.js`, `chat-common.js` |
| Asset routes and read data | `app/main.py`, `app/db/chat_repository.py` |
| Verification | `tests/test_design_views.cjs`, `tests/test_design_read_model.py`, `tests/test_ui_state.cjs`, `evaluation/verify_design_browser.cjs`, `evaluation/verify_operations_browser.py` |

## Verification

- **56 frontend tests passed**, including existing idempotency, stale-response and account-switch cases, plus FIFO ordering, overdue classification, oldest-20 selection, filtering, log content and timeline accuracy.
- **64 relevant Python tests passed**: 63 existing Chat, Desk and account-role cases, plus one session-list ownership/pagination test. Five HTTP cases initially hit the sandbox's local-port restriction and passed when rerun with permission.
- **Real Chrome acceptance passed** with a fresh temporary database, authenticated test account, offline rules, desktop and 390px mobile viewports. It covers login errors, password visibility, navigation, all primary views, order filters and downloads, workshop queue, recommendation confirmation and reload, a two-workshop split, rejection, archive, mobile menu and large text. It also checks retained analytics and order tracking. No page-script or content-security-policy errors were observed.
- **Visual review:** login, dashboard, orders, workshops, queue dialog, single/split recommendations, mobile review and large text screenshots were inspected.
- **`git diff --check` passed.**

Fresh screenshots and `browser.json` are retained in the timestamped `evaluation/live_results/design-*` directory. These generated verification artifacts are ignored by Git.

All verification used temporary data. No production database, real model provider, original requirement files or unrelated in-progress changes were modified. Live LLM quality was not evaluated.

The existing `.venv/bin/python` could not locate its standard library in this environment. Verification used system Python 3.14 with the repository's already installed dependencies on `PYTHONPATH`; the virtual environment was not rebuilt as part of this UI task.

To repeat the browser check with an available Playwright installation:

```sh
PLAYWRIGHT_MODULE=/absolute/path/to/playwright/test.js \
SWEATERCO_PYTHON=/path/to/project/python \
node evaluation/verify_design_browser.cjs
```

The script launches and closes its own local server and temporary database. `CHROME_EXECUTABLE` can override the default macOS Chrome path. Restart an existing application server after updating this code so the new static-asset routes are registered, then reload the browser.
