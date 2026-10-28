# Historical v0.5 manual test walkthrough

This walkthrough records the v0.5 workbench behavior. Start the server, sign in at `http://127.0.0.1:8000`, and use a separate database if the production data must remain untouched. Accepting an allocation changes the selected database.

1. Select Small, Medium, and Large text sizes. Check body text, navigation, inputs, tables, and dialogs. Refresh; the size should persist. Medium is the default.
2. Create a request with “Allocate at the lowest cost.” The legacy session should ask which order to allocate and disable Accept until the missing ID is supplied.
3. Choose an unallocated `READY` order such as `ORD-045` in Edit details, retain lowest cost, exclude `W3`, and update the recommendation. On the clean historical snapshot, the expected proposal was FreshStart/W8, 150 pieces, 150 cost units, and an estimated 2026-04-05 delivery. A changed queue can produce a different real result.
4. Confirm the response is labelled “Proposed — awaiting your approval” and that no production assignment exists yet. Expand calculation and eligibility details to compare pieces, workshop, date, and cost against the summary.
5. Change the objective to Fastest completion and the workshop limit to two. Verify the W3 exclusion remains. An additional “exclude W6” message should append that exclusion.
6. Enter a complex follow-up unsupported by offline rules. It should explain that the requirement was not applied, guide the user to structured edits, and block confirmation of an old draft. Restore a valid recommendation through the form.
7. Click Accept allocation. The reply should indicate saved approval. The Overview recent-allocation summary, Allocation history actor and result, and Production assignment should reflect the committed record.
8. In a new request, enter “Allocate ORD-045 999 pieces.” The field conflict should show the registered quantity. “Use registered order details” resolves only the text conflict; an already assigned order remains ineligible for duplicate allocation.

For the historical DeepSeek path, configure a key on the server following the [setup guide](DEEPSEEK_SETUP_CN.md), restart, and create a **new** session. A later message such as “Please prioritize speed and use W6 for this order” should change the goal and preference while retaining unrelated constraints. An existing offline session does not change modes after restart.

If a DeepSeek session lacks a configured key, a text turn should report a model configuration problem. Structured form edits should remain usable. A service error must never be presented as missing order data or successful approval.

The current v0.6 LLM chat has different Skill and confirmation behavior; use the [current system guide](SYSTEM_GUIDE_CN.md) and [dynamic architecture](AGENT_SKILL_ARCHITECTURE.md) for new Agent acceptance.
