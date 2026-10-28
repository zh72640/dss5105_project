# Historical Gemini integration changelog

Date: 2026-09-14. This record describes the original Parser v1 Gemini transport, before multi-provider registry and native-tool chat. It is not a claim about the currently available Gemini model or live Agent quality.

## Initial Gemini 2.5 Flash integration

The initial change added five files, changed 23, and deleted none. It used the Google Gemini Developer API through official `google-genai==2.23.0`, model `gemini-2.5-flash`, the official endpoint, and only `GEMINI_API_KEY`. The prior OpenAI-compatible transport inside the legacy client was replaced, while schema and business validation stayed in Parser v1.

Key additions were `requirements.txt`, Gemini SDK tests, `evaluation/verify_gemini_live.py` for an explicit smoke or full 60-case run, a machine-readable live status, and this changelog. Configuration samples, README, system guide, known issues, parser/client, pipeline fingerprint, tests, evaluation scripts, and release manifests were updated. The live preflight initially recorded `NOT_RUN / gemini_api_key_missing`; mock transport tests did not consume quota.

The initial local run passed **116 tests**, 60/60 offline golden cases, 30/30 original behavior labels, and unchanged official standard/shock baseline results. Ten SDK tests inspected actual serialized requests with a mock HTTP transport, including endpoint, key source, schema, authentication, rate-limit, timeout, truncation, and client closure. The Parser v1 schema, prompt, rule parser, validator, and migration 001 hashes remained unchanged. No live model call was made without the key.

An added diagnostic `evaluation/diagnose_gemini.py` queried a configured model and attempted a minimal generation through the official SDK while redacting secrets and raw error bodies. It did not change business data. A successful model lookup was documented as insufficient proof that generation would work. No key was available in that execution process to verify the user's project access.

## User-requested Gemini 3.5 Flash change

Later the same day, a requested model change modified 24 files and added or removed none. The then-active legacy client selected `gemini-3.5-flash`, requested minimal thinking, and stopped overriding sampling parameters. Parser and pipeline audit recorded model and thinking level; a null temperature denoted provider default. The idempotency fingerprint included the new configuration, so an old request ID could not be reused with a different model configuration.

Tests checked the official SDK's serialized 3.5 address, no explicit sampling override, minimal thinking, audit fields, HTTP 404 non-retry, and no automatic model switching. Documentation, examples, manifests, and machine results were synchronized. The new full local run passed **117/117 tests**, no skips, with 60/60 offline golden cases, 30/30 behavior labels, and unchanged simulator baselines. Eleven SDK tests still used mock HTTP, so the online status remained `NOT_RUN` without a key. The historical parameter source was Google's [Gemini documentation](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.5).

The source change inventory included configuration samples, README and parser guide, old client/parser/pipeline modules, this and the Week 5/6 changelog, system/next-stage/acceptance guides, manifests, evaluation outputs, and SDK/parser tests. Regenerable virtual environments, Python caches, temporary PDF extraction files, local databases, raw provider errors, and credentials were excluded.

For the later real online run and its rate-limit failure, see [first live Gemini acceptance](GEMINI_LIVE_ACCEPTANCE_CN.md). The current application uses a model registry and LangChain native tool binding for LLM chat; its [architecture guide](AGENT_SKILL_ARCHITECTURE.md) explains that separate path.
