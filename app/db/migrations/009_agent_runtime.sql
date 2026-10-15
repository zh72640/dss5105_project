CREATE TABLE IF NOT EXISTS chat_agent_runs (
 request_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES chat_sessions(session_id),
 fingerprint TEXT NOT NULL, base_version INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('running','finished','failed')),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_agent_run_session_idx ON chat_agent_runs(session_id,status);
CREATE TABLE IF NOT EXISTS chat_agent_tool_calls (
 invocation_key TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES chat_sessions(session_id),
 request_id TEXT NOT NULL REFERENCES chat_agent_runs(request_id),
 skill_name TEXT, skill_hash TEXT, tool_name TEXT NOT NULL,
 arguments_json TEXT NOT NULL, result_json TEXT NOT NULL,
 state_before TEXT NOT NULL, state_after TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_agent_tool_session_idx ON chat_agent_tool_calls(session_id,request_id);
CREATE TABLE IF NOT EXISTS chat_agent_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES chat_sessions(session_id),
 request_id TEXT NOT NULL, event_type TEXT NOT NULL, detail_json TEXT NOT NULL, created_at TEXT NOT NULL
);
