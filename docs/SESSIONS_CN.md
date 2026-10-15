# Sessions

Conversational allocation uses **Chat v2** only: `/api/chat/sessions` and the `/chat` UI.

The earlier `/api/sessions` (`session_v1`) multi-turn API, `app.cli.sessions`, and Desk session editor were **retired**. Historical SQLite session rows may remain; there is no delete-table migration in this stage.

For Chat contracts, confirmation, and owner scoping see [HTTP API](UI_API_CN.md) and [Chat v2](CHAT_V2_CN.md). For the LLM Agent path see [Dynamic Agent architecture](AGENT_SKILL_ARCHITECTURE.md).
