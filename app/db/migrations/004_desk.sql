CREATE TABLE desk_users (
 username TEXT PRIMARY KEY,
 password_hash TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE login_sessions (
 token_hash TEXT PRIMARY KEY,
 username TEXT NOT NULL REFERENCES desk_users(username),
 expires_at REAL NOT NULL
);
CREATE TABLE request_actors (
 request_id TEXT PRIMARY KEY REFERENCES requests(request_id),
 actor TEXT NOT NULL
);
CREATE INDEX login_expiry_idx ON login_sessions(expires_at);
