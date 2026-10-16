ALTER TABLE orders ADD COLUMN version INTEGER NOT NULL DEFAULT 0 CHECK(version>=0);
ALTER TABLE orders ADD COLUMN completed_pieces INTEGER NOT NULL DEFAULT 0 CHECK(completed_pieces BETWEEN 0 AND pieces);
UPDATE orders SET completed_pieces=pieces WHERE state='COMPLETED';
ALTER TABLE working_order ADD COLUMN completed_pieces INTEGER NOT NULL DEFAULT 0 CHECK(completed_pieces BETWEEN 0 AND pieces);
ALTER TABLE working_order ADD COLUMN capacity_at_assignment INTEGER NOT NULL DEFAULT 1 CHECK(capacity_at_assignment>0);
ALTER TABLE working_order ADD COLUMN queue_remaining_days REAL NOT NULL DEFAULT 0 CHECK(queue_remaining_days>=0);
ALTER TABLE workshop_queue ADD COLUMN baseline_queue_days REAL NOT NULL DEFAULT 0 CHECK(baseline_queue_days>=0);
CREATE TABLE lifecycle_events (
 event_id TEXT PRIMARY KEY REFERENCES requests(request_id),
 order_id TEXT NOT NULL REFERENCES orders(order_id),
 action TEXT NOT NULL CHECK(action IN ('complete','cancel','lapse','reassign')),
 actor TEXT NOT NULL, reason TEXT NOT NULL, as_of_date TEXT NOT NULL,
 expected_version INTEGER NOT NULL, applied INTEGER NOT NULL CHECK(applied IN (0,1)),
 before_json TEXT NOT NULL, after_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX lifecycle_order_idx ON lifecycle_events(order_id,created_at);
