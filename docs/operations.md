# Operations dashboard and order tracking

The Overview page presents workshop conditions and order progress using the existing workspace data. Order tracking follows the existing lifecycle: registration, allocation, recorded production and completion. Cancellation, reallocation, reassignment and lapse remain visible in the recorded history. No additional manufacturing stages or database migrations are introduced.

## Using the dashboard

- Open `/` for the dashboard. Hover, focus with the keyboard or tap a chart item to see its values. Press Escape to dismiss its tooltip.
- Compare workshop availability in the donut chart, then inspect queue days, expected defect rates and unit prices in the horizontal bar charts.
- Search orders by ID, customer or product, and filter by status. Select an order to open its journey in Order tracking. The order is retained in the URL so reload restores the selection.
- Use the existing production form to preview and explicitly confirm updates. The dashboard and journey refresh after a successful change. Completed and lapsed orders do not show an action form.

## Data definitions

| Display | Meaning |
| --- | --- |
| Workshop availability | Registered ACTIVE, SUSPENDED and CLOSED status; active means available for allocation, not necessarily idle |
| Workshop workload | Calendar days queued, including imported baseline workload |
| Production quality | Registered expected defect rate; lower is better; this is not an observed inspection result |
| Cost comparison | Registered price per piece in the dataset's cost units; this is not invoiced or realized production cost |
| In production | Orders with active assignments; assignment alone does not prove that physical production has begun |
| Outstanding pieces | Remaining pieces in recorded active allocations; imported baseline workshop workload is not converted into pieces |
| Completed orders | Includes imported completed records |

The journey distinguishes assignment from recorded production. An allocation with no completed pieces leaves production pending. A recorded partial completion advances the production stage. Cancellation retains previously completed quantities and returns the order to allocation. A lapsed order remains distinct from a completed order.

The production trail uses durable decision and lifecycle records and includes actors, timestamps, business dates, quantities, workshops, reasons and record identifiers when available. Unsuccessful attempts are displayed separately from applied changes. Imported records without intermediate events show those milestones as not recorded; the interface does not invent their history.

## Implementation

`app/db/tracking_repository.py` reads the existing audit and lifecycle tables. `app/services/production/tracking.py` derives the presentation from those records and the current order snapshot. `inspect_order` in `app/services/production/lifecycle.py` includes the tracking response in the existing order read transaction and endpoint.

`app/ui/operations.js` and `app/ui/operations.css` implement charts, tooltips, the order list and the icon journey. `app/ui/desk.js` integrates them with the existing data loading, navigation and confirmed production actions. `app/ui/index.html` provides their containers, and `app/main.py` serves the two new static files. No external chart service, CDN or runtime dependency is required.

## Verification

`evaluation/verify_operations_browser.py` checks mouse/keyboard tooltips, search, cancellation and reassignment history, confirmed production updates, reload persistence, incomplete imported history, and a 390px viewport using isolated data. It is included in the [test workflow](testing.md). Generated screenshots and reports remain local.
