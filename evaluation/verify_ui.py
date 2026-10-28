"""Reproducible offline HTTP latency checks using an isolated temporary database.

No real Gemini calls, browser automation or production database writes.
Uses Chat v2 preview/confirm (legacy /api/sessions was retired).
"""
import argparse
import json
import math
import platform
import secrets
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.request import Request, build_opener, HTTPCookieProcessor

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.security import set_password
from app.server import make_server


def measure():
    samples = {}
    with tempfile.TemporaryDirectory(prefix="sweaterco-ui-latency-") as directory:
        path = Path(directory) / "isolated.sqlite3"
        password = secrets.token_urlsafe(24)
        set_password(path, "latency-test", password)
        server = make_server(0, path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = build_opener(HTTPCookieProcessor(CookieJar()))
        base = f"http://127.0.0.1:{server.server_port}"

        def call(label, route, body=None):
            start = time.perf_counter()
            request = Request(base + route, data=json.dumps(body).encode() if body is not None else None,
                              headers={"Content-Type": "application/json"})
            with client.open(request, timeout=10) as response:
                payload = json.load(response)
            samples.setdefault(label, []).append((time.perf_counter() - start) * 1000)
            return payload

        try:
            call("login", "/api/auth/login", {"username": "latency-test", "password": password})
            initial = call("dashboard", "/api/dashboard")
            orders = [o["order_id"] for o in initial["orders"] if o["state"] == "READY"][:20]
            confirmed_ids = set()
            for i, oid in enumerate(orders):
                preview = call("preview", "/api/chat/sessions", {
                    "request_id": f"preview-{i}", "message": f"Allocate {oid}.", "mode": "offline"})
                assert preview["session"]["recommendation"]["status"] == "valid"
                if i < 10:
                    result = call("confirm", f"/api/chat/sessions/{preview['session_id']}/turns", {
                        "expected_version": preview["session_version"],
                        "request_id": f"confirm-{i}", "action": "confirm",
                        "recommendation_id": preview["session"]["recommendation"]["recommendation_id"]})
                    assert result["committed"]
                    confirmed_ids.add('chat-commit-' + preview['session']['recommendation']['recommendation_id'])
                call("dashboard", "/api/dashboard")
                call("workshops", "/api/workshops")
                call("audit", "/api/audit")
            exported = call("export_json", "/api/audit/export?format=json")
            # Chat v2 previews live in chat_turns/recommendations; business audit
            # exports contain only the explicit confirmations from this run.
            assert exported["total"] == len(confirmed_ids) == len(exported["items"])
            assert {item['request_id'] for item in exported['items']} == confirmed_ids
            assert all(item['approved'] and item['actor'] == 'latency-test' for item in exported['items'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    metrics = {name: {"samples": len(values), "p50_ms": round(sorted(values)[len(values) // 2], 2),
                      "p95_ms": round(sorted(values)[math.ceil(len(values) * .95) - 1], 2),
                      "max_ms": round(max(values), 2)} for name, values in samples.items()}
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
            "scope": "Local HTTP, authenticated, offline Chat v2, 120 seeded orders and 8 workshops. "
                     "Not browser paint time, concurrent load or Gemini latency.",
            "metrics": metrics, "all_observed_responses_under_3_seconds": all(max(v) < 3000 for v in samples.values()),
            "preview_count": len(orders), "confirmed_count": len(confirmed_ids), "exported_decisions": len(exported['items']),
            "production_database_touched": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'evaluation/results/ui_latency.json')
    args = parser.parse_args()
    result = measure()
    out = args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["all_observed_responses_under_3_seconds"] else 1)
