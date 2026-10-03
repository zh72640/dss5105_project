CREATE TABLE sessions (
 session_id TEXT PRIMARY KEY,
 state TEXT NOT NULL CHECK(state IN ('ACTIVE','AWAITING_CLARIFICATION','CLOSED')),
 version INTEGER NOT NULL DEFAULT 0 CHECK(version>=0),
 objective TEXT NOT NULL, backend TEXT NOT NULL, as_of_date TEXT NOT NULL,
 draft_json TEXT NOT NULL, blockers_json TEXT NOT NULL,
 reviewed_order_version INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE session_messages (
 session_id TEXT NOT NULL REFERENCES sessions(session_id),
 sequence INTEGER NOT NULL CHECK(sequence>0),
 request_id TEXT NOT NULL REFERENCES requests(request_id),
 role TEXT NOT NULL CHECK(role IN ('user','assistant')),
 action TEXT NOT NULL CHECK(action IN ('message','replace','confirm','close')),
 content TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(session_id,sequence), UNIQUE(request_id,role)
);
CREATE INDEX requests_session_idx ON requests(session_id,request_date_time);
