"""Local-only JSON API and existing UI. Start with python3 -m app.server."""
import argparse
import json
import os
import re
import sqlite3
import threading
import time
from datetime import date
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs
from app import auth, desk
from app import APP_VERSION
from app.db.database import Database
from app.pipeline import PIPELINE_VERSION, process_request
from app.lifecycle import inspect_order, process_event
from app.sessions import create_session, inspect_session, session_turn

ROOT = Path(__file__).resolve().parents[1]


def make_server(port=8000, db_path=None, backend="offline", as_of=date(2026, 4, 1), *, require_auth=True):
    db_path = str(db_path or ROOT / "runtime/dispatch.sqlite3")
    if db_path == ":memory:":
        raise ValueError("The HTTP server requires a file database shared by its request threads.")
    with Database(db_path):
        pass
    login_attempts = []
    login_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, data, content_type="application/json; charset=utf-8", headers=None):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            if urlparse(self.path).path != "/legacy":
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def token(self):
            try:
                cookies = SimpleCookie(self.headers.get("Cookie", ""))
                return cookies[auth.COOKIE].value if auth.COOKIE in cookies else ""
            except CookieError:
                return ""

        def user(self):
            return auth.identify(db_path, self.token()) if require_auth else "local-demo"

        def do_GET(self):
            path = urlparse(self.path).path
            assets = {"/": ("index.html", "text/html"), "/legacy": ("legacy.html", "text/html"),
                      "/sessions.js": ("sessions.js", "text/javascript"), "/desk.js": ("desk.js", "text/javascript"),
                      "/desk.css": ("desk.css", "text/css")}
            if path in assets:
                filename, mime = assets[path]
                return self.send(200, (ROOT / "app/ui" / filename).read_bytes(), mime + "; charset=utf-8")
            if path == "/api/health":
                return self.send(200, {"status": "ok", "backend": backend, "as_of_date": as_of.isoformat(),
                                       "version": APP_VERSION, "pipeline_version": PIPELINE_VERSION})
            try:
                username = self.user()
                if path == "/api/auth/me":
                    with Database(db_path) as db:
                        setup = db.connection.execute("SELECT COUNT(*) FROM desk_users").fetchone()[0] == 0
                    return self.send(200, {"username": username, "auth_required": require_auth, "setup_required": require_auth and setup})
                if not username:
                    return self.send(401, {"error": "LOGIN_REQUIRED"})
                params = parse_qs(urlparse(self.path).query)
                query = params.get("q", [""])[0].strip()[:200]
                if path == "/api/dashboard":
                    return self.send(200, desk.dashboard(db_path, as_of))
                if path == "/api/workshops":
                    with Database(db_path) as db:
                        items = desk.workshops(db.connection, as_of)
                    status = params.get("status", [""])[0]
                    category = params.get("category", [""])[0]
                    items = [w for w in items if (not query or query.casefold() in (w["workshop_id"] + " " + w["name"]).casefold())
                             and (not status or w["status"] == status) and (not category or category in w["makes"])]
                    return self.send(200, {"items": items, "business_date": as_of.isoformat()})
                if path in ("/api/audit", "/api/audit/export") or path.startswith("/api/audit/"):
                    export = path == "/api/audit/export"
                    detail = unquote(path[len("/api/audit/"):]) if path.startswith("/api/audit/") and not export else None
                    page, size = int(params.get("page", ["1"])[0]), int(params.get("page_size", ["25"])[0])
                    if not 1 <= page <= 1000000 or not 1 <= size <= 100:
                        return self.send(400, {"error": "INVALID_PAGINATION"})
                    # Export always includes ALL decisions, independent of list filters and pagination.
                    payload = desk.audit(db_path, query="" if export else query,
                        status="" if export else params.get("status", [""])[0], page=page, page_size=size, export=export, request_id=detail)
                    if export:
                        fmt = params.get("format", ["json"])[0]
                        if fmt not in ("csv", "json"):
                            return self.send(400, {"error": "INVALID_EXPORT_FORMAT"})
                        body = desk.audit_csv(payload["items"]) if fmt == "csv" else json.dumps(payload, ensure_ascii=False, indent=2).encode()
                        return self.send(200, body, "text/csv; charset=utf-8" if fmt == "csv" else "application/json; charset=utf-8",
                                         {"Content-Disposition": f'attachment; filename="sweaterco-allocation-history.{fmt}"'})
                    if detail:
                        return self.send(200, payload["items"][0]) if payload["items"] else self.send(404, {"error": "AUDIT_NOT_FOUND"})
                    return self.send(200, payload)
            except ValueError:
                return self.send(400, {"error": "INVALID_QUERY"})
            except (sqlite3.Error, OSError):
                return self.send(503, {"error": "DB_ERROR"})
            if path.startswith("/api/sessions/"):
                try:
                    session = inspect_session(unquote(path[len("/api/sessions/"):]), db_path=db_path)
                    return self.send(200, session) if session else self.send(404, {"error": "SESSION_NOT_FOUND"})
                except (sqlite3.Error, OSError, ValueError):
                    return self.send(503, {"error": "DB_ERROR"})
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
            session_route = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,128})/turns", self.path)
            if self.path not in ("/api/requests", "/api/events", "/api/sessions", "/api/auth/login", "/api/auth/logout") and not session_route:
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
                if self.path == "/api/auth/login":
                    if not isinstance(data, dict) or set(data) != {"username", "password"}:
                        return self.send(400, {"error": "INVALID_FIELDS"})
                    with login_lock:
                        now = time.monotonic()
                        login_attempts[:] = [t for t in login_attempts if now - t < 60]
                        if len(login_attempts) >= 10:
                            return self.send(429, {"error": "LOGIN_RATE_LIMIT", "message": "Too many attempts. Try again in one minute."})
                        login_attempts.append(now)
                    token = auth.login(db_path, data["username"], data["password"])
                    if not token:
                        return self.send(401, {"error": "INVALID_CREDENTIALS"})
                    return self.send(200, {"username": data["username"]}, headers={"Set-Cookie":
                        f"{auth.COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={auth.TTL}"})
                username = self.user()
                if not username:
                    return self.send(401, {"error": "LOGIN_REQUIRED"})
                if self.path == "/api/auth/logout":
                    auth.logout(db_path, self.token())
                    return self.send(200, {"success": True}, headers={"Set-Cookie":
                        f"{auth.COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
                if self.path == "/api/sessions" or session_route:
                    allowed = {"session_id", "objective"} if not session_route else {"request_id", "expected_version", "action", "message"}
                    required = set() if not session_route else {"request_id", "expected_version"}
                    if not isinstance(data, dict) or set(data) - allowed or not required <= set(data):
                        return self.send(400, {"error": "INVALID_FIELDS"})
                    payload = (session_turn(session_route[1], **data, actor=username, db_path=db_path) if session_route else
                               create_session(**data, backend=backend, as_of=as_of, db_path=db_path))
                    codes = payload.get("result", {}).get("reason_codes", [])
                    status = (400 if "INVALID_ARGUMENT" in codes else 404 if "SESSION_NOT_FOUND" in codes else
                              503 if "DB_ERROR" in codes else 409 if any(c in codes for c in
                              ("IDEMPOTENCY_CONFLICT", "SESSION_VERSION_CONFLICT", "SESSION_CLOSED", "ORDER_VERSION_CONFLICT")) else 200)
                    return self.send(status, payload)
                if self.path == "/api/events":
                    required = {"action", "order_id", "actor", "reason", "expected_version", "event_id"}
                    allowed = required | {"workshop_id", "pieces", "objective", "exclusion", "max_workshops",
                                          "preferred_workshop", "deadline_required"}
                    if not isinstance(data, dict) or set(data) - allowed or not required <= set(data):
                        return self.send(400, {"error": "INVALID_FIELDS"})
                    if require_auth:
                        data["actor"] = username
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
                    request_id=data.get("request_id"), db_path=db_path, backend=backend, as_of=as_of, actor=username)
                codes = payload["result"]["reason_codes"]
                status = 409 if "IDEMPOTENCY_CONFLICT" in codes else 400 if "INVALID_ARGUMENT" in codes else 503 if payload["result"]["decision_status"] == "ERROR" else 200
                return self.send(status, payload)
            except (ValueError, UnicodeError):
                return self.send(400, {"error": "INVALID_JSON"})
            except (sqlite3.Error, OSError):
                return self.send(503, {"error": "DB_ERROR"})

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
    parser.add_argument("--no-auth", action="store_true", help="Explicit local demonstration mode without login; approvals use local-demo.")
    args = parser.parse_args()
    server = make_server(args.port, args.db, args.backend, args.as_of, require_auth=not args.no_auth)
    print(f"SweaterCo {args.backend} | http://127.0.0.1:{server.server_port} | business date {args.as_of}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
