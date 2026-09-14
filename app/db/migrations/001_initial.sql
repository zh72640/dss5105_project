CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE orders (
 order_id TEXT PRIMARY KEY, customer TEXT NOT NULL, product TEXT NOT NULL,
 category TEXT NOT NULL, pieces INTEGER NOT NULL CHECK(pieces>0),
 order_date TEXT NOT NULL, due_date TEXT NOT NULL, source_status TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('READY','WORKING','UNASSIGNED','COMPLETED','LAPSED'))
);
CREATE TABLE workshops (
 workshop_id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
 capacity_pieces_per_day INTEGER NOT NULL CHECK(capacity_pieces_per_day>0),
 pickup_lead_days INTEGER NOT NULL CHECK(pickup_lead_days>=0),
 defect_rate REAL NOT NULL CHECK(defect_rate BETWEEN 0 AND 1),
 cost_per_piece REAL NOT NULL CHECK(cost_per_piece>=0), makes TEXT NOT NULL,
 status TEXT NOT NULL, max_batch_pieces INTEGER CHECK(max_batch_pieces>0), notes TEXT NOT NULL
);
CREATE TABLE workshop_queue (
 workshop_id TEXT PRIMARY KEY REFERENCES workshops(workshop_id),
 current_queue_days REAL NOT NULL CHECK(current_queue_days>=0), as_of_date TEXT NOT NULL
);
CREATE TABLE requests (
 request_id TEXT PRIMARY KEY, request_date_time TEXT NOT NULL, fingerprint TEXT NOT NULL,
 original_message TEXT NOT NULL, status TEXT NOT NULL, response_json TEXT NOT NULL,
 telemetry_json TEXT NOT NULL, session_id TEXT
);
CREATE TABLE request_parsing_history (
 request_id TEXT PRIMARY KEY REFERENCES requests(request_id), request_date_time TEXT NOT NULL,
 original_message TEXT NOT NULL, parsed_order_id TEXT, parsed_customer TEXT, parsed_product TEXT,
 parsed_category TEXT, parsed_pieces INTEGER CHECK(parsed_pieces>0), parsed_order_date TEXT,
 parsed_due_date TEXT, parsed_objective TEXT, parsed_exclusion TEXT NOT NULL,
 parsed_num_workshop_allowed INTEGER CHECK(parsed_num_workshop_allowed>0),
 parsed_preferred_workshop TEXT, parsed_deadline_required INTEGER NOT NULL,
 parse_status TEXT NOT NULL, missing_fields TEXT NOT NULL, ambiguities TEXT NOT NULL
);
CREATE TABLE working_order (
 order_id TEXT NOT NULL REFERENCES orders(order_id), workshop_id TEXT NOT NULL REFERENCES workshops(workshop_id),
 request_id TEXT NOT NULL REFERENCES requests(request_id), pieces INTEGER NOT NULL CHECK(pieces>0),
 estimated_days REAL NOT NULL, estimated_cost REAL NOT NULL, objective TEXT NOT NULL,
 assigned_at TEXT NOT NULL, PRIMARY KEY(order_id, workshop_id)
);
CREATE TABLE unassigned_order (
 order_id TEXT PRIMARY KEY REFERENCES orders(order_id), request_id TEXT NOT NULL REFERENCES requests(request_id),
 reason TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE completed_order (order_id TEXT PRIMARY KEY REFERENCES orders(order_id), completed_at TEXT);
CREATE TABLE lapsed_order (order_id TEXT PRIMARY KEY REFERENCES orders(order_id), reason TEXT NOT NULL, lapsed_at TEXT NOT NULL);
CREATE TABLE decision_log (
 decision_id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL UNIQUE REFERENCES requests(request_id),
 order_id TEXT REFERENCES orders(order_id), decision_status TEXT NOT NULL,
 reason_codes TEXT NOT NULL, objective TEXT, decision_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX working_request_idx ON working_order(request_id);
