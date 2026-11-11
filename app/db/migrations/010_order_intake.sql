CREATE TABLE order_intake_reviews (
 review_id TEXT PRIMARY KEY,
 request_id TEXT NOT NULL UNIQUE,
 actor TEXT NOT NULL,
 order_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL,
 review_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX order_intake_reviews_order_idx ON order_intake_reviews(order_id, created_at);
CREATE TABLE order_intake_decisions (
 request_id TEXT PRIMARY KEY,
 review_id TEXT NOT NULL UNIQUE REFERENCES order_intake_reviews(review_id),
 actor TEXT NOT NULL,
 action TEXT NOT NULL CHECK(action IN ('create','update','reject')),
 fingerprint TEXT NOT NULL,
 decision_json TEXT NOT NULL,
 response_json TEXT NOT NULL,
 status_code INTEGER NOT NULL,
 created_at TEXT NOT NULL
);
