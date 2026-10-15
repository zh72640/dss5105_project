CREATE TABLE jobs (
 job_id TEXT PRIMARY KEY,
 kind TEXT NOT NULL,
 status TEXT NOT NULL,
 session_id TEXT,
 actor TEXT,
 request_json TEXT NOT NULL,
 result_json TEXT,
 progress_json TEXT NOT NULL,
 error TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX jobs_status_updated_idx ON jobs(status, updated_at);
