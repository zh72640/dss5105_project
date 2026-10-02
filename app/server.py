"""Local-only JSON API and existing UI. Start with python3 -m app.server."""
import argparse
import json
import os
import sqlite3
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from app.db.database import Database
from app.pipeline import PIPELINE_VERSION, process_request
from app.lifecycle import inspect_order, process_event

ROOT = Path(__file__).resolve().parents[1]


def make_server(port=8000, db_path=None, backend="offline", as_of=date(2026, 4, 1)):
    db_path = str(db_path or ROOT / "runtime/dispatch.sqlite3")
    if db_path == ":memory:":
        raise ValueError("The HTTP server requires a file database shared by its request threads.")
    with Database(db_path):
        pass

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, data, content_type="application/json; charset=utf-8"):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                return self.send(200, (ROOT / "app/ui/index.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/api/health":
                return self.send(200, {"status": "ok", "backend": backend, "as_of_date": as_of.isoformat(), "version": PIPELINE_VERSION})
            if path.startswith("/api/orders/"):
                try:
                    order = inspect_order(unquote(path[len("/api/orders/"):]), db_path=db_path)
                    return self.send(200, order) if order else self.send(404, {"error": "ORDER_NOT_FOUND"})
                except (sqlite3.Error, OSError, ValueError):
                    return self.send(503, {"error": "DB_ERROR"})
            if path == "/api/history":
                try:
                    with Database(db_path) as db:
                        rows = db.connection.execute("SELECT request_id,request_date_time,status,response_json FROM requests ORDER BY request_date_time DESC LIMIT 30").fetchall()
                        return self.send(200, [{"request_id": r["request_id"], "time": r["request_date_time"], "status": r["status"],
                            "order_id": (json.loads(r["response_json"]).get("parsed") or
                                         json.loads(r["response_json"]).get("event") or {}).get("order_id")} for r in rows])
                except sqlite3.Error:
                    return self.send(503, {"error": "DB_ERROR"})
            return self.send(404, {"error": "NOT_FOUND"})

        def do_POST(self):
            if self.path not in ("/api/requests", "/api/events"):
                return self.send(404, {"error": "NOT_FOUND"})
            # JSON-only, same-origin local endpoint; no credential-bearing CORS.
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"):
                return self.send(403, {"error": "ORIGIN_REJECTED"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415, {"error": "JSON_REQUIRED"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 50000:
                    return self.send(413, {"error": "INVALID_BODY_SIZE"})
                data = json.loads(self.rfile.read(length))
                if self.path == "/api/events":
                    required = {"action", "order_id", "actor", "reason", "expected_version", "event_id"}
                    allowed = required | {"workshop_id", "pieces", "objective", "exclusion", "max_workshops",
                                          "preferred_workshop", "deadline_required"}
                    if not isinstance(data, dict) or set(data) - allowed or not required <= set(data):
                        return self.send(400, {"error": "INVALID_FIELDS"})
                    payload = process_event(**data, db_path=db_path, as_of=as_of)
                    codes = payload["result"]["reason_codes"]
                    status = (400 if "INVALID_ARGUMENT" in codes else 404 if "ORDER_NOT_FOUND" in codes else
                              503 if payload["result"]["decision_status"] == "ERROR" else
                              409 if not payload["result"]["success"] else 200)
                    # Key reuse with different input is a conflict, not an infrastructure error.
                    if "IDEMPOTENCY_CONFLICT" in codes:
                        status = 409
                    return self.send(status, payload)
                if not isinstance(data, dict) or set(data) - {"message", "objective", "request_id"}:
                    return self.send(400, {"error": "INVALID_FIELDS"})
                if not isinstance(data.get("message"), str) or not data["message"].strip() or len(data["message"]) > 10000:
                    return self.send(400, {"error": "INVALID_MESSAGE"})
                if "objective" in data and not isinstance(data["objective"], str):
                    return self.send(400, {"error": "INVALID_OBJECTIVE"})
                payload = process_request(data["message"], data.get("objective", "min_delay"),
                    request_id=data.get("request_id"), db_path=db_path, backend=backend, as_of=as_of)
                codes = payload["result"]["reason_codes"]
                status = 409 if "IDEMPOTENCY_CONFLICT" in codes else 400 if "INVALID_ARGUMENT" in codes else 503 if payload["result"]["decision_status"] == "ERROR" else 200
                return self.send(status, payload)
            except (ValueError, UnicodeError):
                return self.send(400, {"error": "INVALID_JSON"})

        def log_message(self, fmt, *args):
            # No raw message or API credentials in server logs.
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default=str(ROOT / "runtime/dispatch.sqlite3"))
    parser.add_argument("--backend", choices=["offline", "llm"], default=os.getenv("PARSER_BACKEND", "offline"))
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 4, 1))
    args = parser.parse_args()
    server = make_server(args.port, args.db, args.backend, args.as_of)
    print(f"SweaterCo {args.backend} | http://127.0.0.1:{server.server_port} | business date {args.as_of}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
