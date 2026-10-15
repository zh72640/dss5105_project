CREATE TABLE chat_sessions (
 session_id TEXT PRIMARY KEY, owner_username TEXT NOT NULL,
 creation_key TEXT NOT NULL UNIQUE, creation_fingerprint TEXT NOT NULL,
 title TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('OPEN','ARCHIVED')),
 version INTEGER NOT NULL DEFAULT 0, business_date TEXT NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('offline','llm')), model_key TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX chat_owner_idx ON chat_sessions(owner_username,updated_at,session_id);
CREATE TABLE chat_allocation_tasks (
 task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL UNIQUE REFERENCES chat_sessions(session_id),
 task_version INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL CHECK(state IN ('COLLECTING','BLOCKED','READY','RECOMMENDED','CONFIRMED','CANCELLED')),
 draft_json TEXT NOT NULL, sources_json TEXT NOT NULL, changes_json TEXT NOT NULL,
 issues_json TEXT NOT NULL, report_json TEXT NOT NULL
);
CREATE TABLE chat_turns (
 turn_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES chat_sessions(session_id),
 request_id TEXT NOT NULL UNIQUE, fingerprint TEXT NOT NULL, base_version INTEGER NOT NULL,
 action TEXT NOT NULL, input_json TEXT NOT NULL, response_json TEXT NOT NULL,
 telemetry_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE chat_messages (
 message_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES chat_sessions(session_id),
 turn_id TEXT NOT NULL REFERENCES chat_turns(turn_id), sequence INTEGER NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
 metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(session_id,sequence), UNIQUE(turn_id,role)
);
CREATE TABLE chat_recommendations (
 recommendation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES chat_sessions(session_id),
 task_id TEXT NOT NULL REFERENCES chat_allocation_tasks(task_id), task_version INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('valid','superseded','confirmed')),
 facts_hash TEXT NOT NULL, plan_hash TEXT NOT NULL, result_json TEXT NOT NULL,
 confirmation_turn_id TEXT REFERENCES chat_turns(turn_id), business_request_id TEXT UNIQUE REFERENCES requests(request_id),
 feedback_message_id TEXT, committed_result_json TEXT, created_at TEXT NOT NULL
);
CREATE INDEX chat_recommendation_idx ON chat_recommendations(session_id,created_at,recommendation_id);
