"""Reproducible offline HTTP latency checks using an isolated temporary database.

No real Gemini calls, browser automation or production database writes.
"""
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

from app.auth import set_password
from app.server import make_server


def measure():
    samples = {}
    with tempfile.TemporaryDirectory(prefix='sweaterco-ui-latency-') as directory:
        path = Path(directory) / 'isolated.sqlite3'
        password = secrets.token_urlsafe(24)
        set_password(path, 'latency-test', password)
        server = make_server(0, path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = build_opener(HTTPCookieProcessor(CookieJar()))
        base = f'http://127.0.0.1:{server.server_port}'

        def call(label, route, body=None):
            start = time.perf_counter()
            request = Request(base + route, data=json.dumps(body).encode() if body is not None else None,
                              headers={'Content-Type': 'application/json'})
            with client.open(request, timeout=10) as response:
                payload = json.load(response)
            samples.setdefault(label, []).append((time.perf_counter() - start) * 1000)
            return payload

        try:
            call('login', '/api/auth/login', {'username': 'latency-test', 'password': password})
            initial = call('dashboard', '/api/dashboard')
            orders = [o['order_id'] for o in initial['orders'] if o['state'] == 'READY'][:20]
            for i, oid in enumerate(orders):
                sid = f'latency-{i}'
                call('create_session', '/api/sessions', {'session_id': sid})
                preview = call('preview', f'/api/sessions/{sid}/turns',
                    {'expected_version': 0, 'request_id': f'preview-{i}', 'message': f'Allocate {oid}.'})
                assert preview['result']['decision_status'] == 'REVIEW'
                if i < 10:
                    result = call('confirm', f'/api/sessions/{sid}/turns',
                        {'expected_version': 1, 'request_id': f'confirm-{i}', 'action': 'confirm'})
                    assert result['committed']
                call('dashboard', '/api/dashboard')
                call('workshops', '/api/workshops')
                call('audit', '/api/audit')
            exported = call('export_json', '/api/audit/export?format=json')
            assert exported['total'] == 30 and len(exported['items']) == 30
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    metrics = {name: {'samples': len(values), 'p50_ms': round(sorted(values)[len(values)//2], 2),
                     'p95_ms': round(sorted(values)[math.ceil(len(values)*.95)-1], 2),
                     'max_ms': round(max(values), 2)} for name, values in samples.items()}
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'python': platform.python_version(),
            'scope': 'Local HTTP, authenticated, offline rules, 120 seeded orders and 8 workshops. Not browser paint time, concurrent load or Gemini latency.',
            'metrics': metrics, 'all_observed_responses_under_3_seconds': all(max(v)<3000 for v in samples.values()),
            'preview_count': 20, 'confirmed_count': 10, 'exported_decisions': 30,
            'production_database_touched': False}


if __name__ == '__main__':
    result = measure()
    out = ROOT / 'evaluation/results/ui_latency.json'
    out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['all_observed_responses_under_3_seconds'] else 1)
