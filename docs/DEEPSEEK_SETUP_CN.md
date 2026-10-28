# DeepSeek local configuration

This guide originated with MVP v0.5 on 2026-10-07. Keep the API key in the server process environment. Do not put it in a chat message, source file, Git commit, browser input, or diagnostic output. A browser sees only backend/configured/model status. The project does not automatically load `.env`; use the supported environment-loading option at startup when appropriate.

## Start with a key

Set `DEEPSEEK_API_KEY` in your own terminal without echoing it, then start a new server process. On macOS with zsh, the historical non-echoing example is:

```zsh
source .venv/bin/activate
read -rs 'DEEPSEEK_API_KEY?DeepSeek API key (hidden): '
printf '\n'
export DEEPSEEK_API_KEY
python -m app.server --backend deepseek
```

On Windows PowerShell, obtain the key through your preferred secret manager or a hidden prompt rather than placing its value in command history. An environment change does not update an already running server: restart it and create a new session to use a changed provider or model. Existing sessions keep their creation-time mode and model.

The legacy parser backend chooses DeepSeek automatically when a key is present and no `PARSER_BACKEND` is supplied; an explicit `--backend` has highest precedence. For the current dynamic chat, select an LLM session and a configured DeepSeek model in the UI or API. The application model registry binds native tool schemas for DeepSeek; the older parser transport remains a separate compatibility path.

| Variable | Historical default | Purpose |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | None | Server credential. |
| `DEEPSEEK_MODEL` | `deepseek-flash` | Single-model legacy parser model, with a validated `deepseek-*` name. |
| `DEEPSEEK_MODELS` | None | Current model-registry entries when multiple DeepSeek models are configured. |
| `DEEPSEEK_TIMEOUT_SECONDS` | 30 | Legacy HTTP timeout, positive and at most 300 seconds. |
| `PARSER_BACKEND` | Automatic | Legacy parser selection. |

The legacy transport sends nonstreaming requests to `https://api.deepseek.com/chat/completions`, requests JSON output, limits response size, and validates returned fields and constraints before planning. Current LLM chat uses the model registry and native tool calls instead of parsing a JSON execution plan. Model and API availability can change, so consult the provider's current documentation before choosing a paid model.

The historical macOS Keychain option stored an item named `sweaterco-deepseek` under the local username and loaded it into the process environment:

```zsh
export DEEPSEEK_API_KEY="$(security find-generic-password -s sweaterco-deepseek -a "$USER" -w)"
python -m app.server --backend deepseek
```

Do not print the key to confirm setup. After login, `GET /api/ai/status` reports backend, configured flag, and model without the key. `configured=true` means local configuration exists, not that the provider has accepted a real request. Test one new session against an unallocated `READY` order, inspect the recommendation and execution trace, then explicitly confirm only if appropriate. Missing key, authentication, balance, rate limit, connection, or invalid response errors should be reported as provider problems, never as missing order data or a successful allocation.

At v0.5, mocked HTTPS tests covered response, retry, errors, redirect refusal, and key omission from telemetry; no real DeepSeek call was claimed. The current dynamic-Agent suite similarly verifies native tool binding and the graph with a scripted model. A live provider run is still a separate acceptance activity.
