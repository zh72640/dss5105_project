# MVP v0.5: DeepSeek, recent allocations, and actionable clarification

Historical update: 2026-10-07. The release continued the English course-presentation UI. Database schema remained v4; Parser v1, legacy Session v1, and the core allocation algorithm kept their earlier contracts. The current application has since advanced to schema v9 and a separate dynamic LLM chat path.

| User need | v0.5 change |
| --- | --- |
| Keep a DeepSeek key on the local server | Added environment-based backend selection, model and timeout configuration, configuration status, and stable service errors. |
| Understand a recommendation quickly | Put a factual summary of order, total and per-workshop pieces, ETA, cost, and objective before detailed calculations; distinguish proposed from approved. |
| Review recent decisions | Added “What was assigned?” with the five most recent approvals and a path to production progress. |
| Resolve vague clarification | Display missing fields, conflicts, examples, and next actions separately; added Edit details as a model-independent form. |
| Revise constraints without fixed commands | DeepSeek follow-up parsing handled a new sentence while preserving unrelated local draft fields; structured edits worked with every backend. |
| Read the workbench comfortably | Added Small, Medium, and Large text sizes, persisted in the browser. Root sizes were 14, 16, and 20 px, with relative sizing across navigation, tables, dialogs, and inputs. |
| Reduce visual density | Collapsed raw fields, candidate lists, and calculation details by default, leaving the summary and approval action prominent. |

Messages and form edits saved only a draft. Accept allocation performed a versioned, fresh queue and workshop check before production write. The final summary used the actual confirmed result, which could differ from an older preview. Explicit “Use registered order details” cleared conflicting entered product, quantity, or date values without modifying order master data.

Unsupported requirements such as a budget cap or exact split remained blockers; unrelated edits did not silently clear them. The DeepSeek key stayed on the server, out of browser inputs, Git, logs, and database rows. Natural-language summaries came from actual allocation data without another paid model request, and offline mode displayed the same factual summaries.

The release added tests for DeepSeek integration and assistant/workbench behavior and extended HTTP and frontend controller tests. See the [v0.5 acceptance record](V05_ACCEPTANCE_CN.md), [DeepSeek setup](DEEPSEEK_SETUP_CN.md), and [deployment guide](DEPLOYMENT_CN.md). The release did not reset existing passwords, deploy publicly, or complete a real DeepSeek quality evaluation. Its then-existing v4 database could be reused after backup and restart.
