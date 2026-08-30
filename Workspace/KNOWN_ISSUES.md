# Known issues and next steps

- `parse_request()` is a deterministic golden-case adapter, not a production LLM
  integration. Its interface is stable so an LLM structured-output adapter can be
  substituted without changing downstream modules.
- The HTML UI uses a checked-in R09 payload. Connect it to a small API in the next
  integration sprint.
- Allocation uses the dataset's initial queue snapshot. Stateful queue updates are
  handled by the shared simulator, not the single-request demo pipeline.
- Split allocation and human escalation are represented in the schema but are not
  implemented yet.
- The language ground truth is an initial behaviour-level pass and needs a second
  human review before it is treated as evaluation truth.
- Shock response is not adaptive yet; Week 4 only captures the official baselines.

