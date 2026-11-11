CREATE TABLE chat_order_registration (
 session_id TEXT PRIMARY KEY REFERENCES chat_sessions(session_id),
 task_id TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL CHECK(status IN ('COLLECTING','REVIEW','COMPLETED','CANCELLED')),
 draft_json TEXT NOT NULL,
 issues_json TEXT NOT NULL,
 review_id TEXT REFERENCES order_intake_reviews(review_id),
 updated_at TEXT NOT NULL
);
CREATE TABLE chat_registration_steps (
 request_id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES chat_sessions(session_id),
 fingerprint TEXT NOT NULL,
 result_json TEXT NOT NULL
);
