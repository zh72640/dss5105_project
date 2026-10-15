# First live Gemini acceptance record

Date: 2026-10-02. This historical run used the then-configured Google Gemini Developer API, official SDK, and `GEMINI_API_KEY`. No credential was placed in code, documentation, or commits. The run predates the dynamic Agent refactor and evaluates the earlier parser path, not native tool calling.

## Result

A real end-to-end smoke request allocated an order and safely replayed the same request ID. The complete 60-case evaluation was **ACCEPTANCE_FAILED**.

| Measure | Observed result |
| --- | --- |
| Exact matches | 14 / 60 |
| Valid on first parse | 9 / 60 (15%) |
| Valid after retry and core-field matches | 14 / 60 (23.33%) |
| Final service failures | 46 cases with `gemini_http_429` |
| Service errors across all attempts | 91 HTTP 429 and 6 HTTP 503 |
| Cases with a model output | 14; each matched the checked fields |
| Invented values in observed valid outputs | 0 among 549 missing-field slots; many other cases had no output, so this is not a general zero-invention claim |

See [full metrics](../evaluation/results/parser_llm_metrics.json) and [status](../evaluation/results/gemini_live_status.json). Raw and validated runs were kept locally under ignored `evaluation/live_results/`, without publishing credentials or raw service error bodies. The parser, prompt, and model settings were unchanged between this pre-lifecycle v0.1 run and the subsequent v0.2 release.

The direct evidence is rate limiting. HTTP 429 alone does not distinguish minute quota, daily quota, or service capacity. The 23.33% aggregate result cannot be interpreted as model accuracy for cases that produced no output. All 60 cases remain in the acceptance denominator.

## Evaluation changes made with this record

- Reports gained counts of final errors, errors per attempt, and cases with actual model output.
- `live_llm_validated` uses the planned thresholds: at least 98% first-pass validity, at least 90% core-field accuracy, and zero observed invention.
- `--interval-seconds` (0–60) sets a delay between cases; default zero keeps prior behavior. It does not change the parser's one-retry limit or guarantee sufficient quota.
- Simulated rate-limit and invalid-interval tests ensure service failures remain in the denominator.

## Follow-up for a new live run

Check project quota and the 429 cause, then run a smoke test before a quota-aware full run. Keep a distinct output directory for the new run and compare complete metrics rather than overwriting this failure baseline.

```bash
python evaluation/verify_gemini_live.py
python evaluation/verify_gemini_live.py --full --interval-seconds 10
```

Ten seconds is illustrative, not a quota guarantee. If 429s persist, add bounded backoff and request limiting while ensuring no failed parse reaches allocation. A second team member should review labels and create an independent holdout set rather than changing expected labels to match the program.
