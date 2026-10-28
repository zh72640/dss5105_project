"""Evaluate current Chat v2 intake without confirming or mutating production.

Use --cases JSONL for independently labelled inputs. The bundled 30 requests are
development data; their historical labels are provisional and predate Chat v2.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import re
import sys
import tempfile
import time
from datetime import date, datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.model_settings import load_model_settings
from app.db.database import Database
from app.llm.registry import ModelRegistry
from app.services.chat import service as chat


def original_cases():
    texts = {}
    for line in (ROOT / 'data/dispatch_requests.txt').read_text().splitlines():
        match = re.match(r'^(R\d+) \[[^]]+\] [^:]+: (.*)$', line)
        if match:
            texts[match[1]] = match[2]
    with (ROOT / 'evaluation/language_ground_truth.csv').open(newline='') as handle:
        return [{'id': row['request_id'], 'message': texts[row['request_id']],
                 'expected_behavior': row['expected_behavior']} for row in csv.DictReader(handle)]


def behavior(response):
    """Explicit action mapping; ALLOCATE means a proposal, never a commit."""
    if response.get('http_status', 200) >= 500:
        return 'SERVICE_ERROR'
    if response.get('session', {}).get('recommendation'):
        return 'ALLOCATE'
    issues = response.get('validation_report', {}).get('blocking_issues', []) + response.get('issues', [])
    codes = {item['code'] for item in issues}
    if codes & {'ORDER_NOT_FOUND', 'INVALID_REQUEST', 'UNSUPPORTED_REQUEST'}:
        return 'DECLINE'
    if any(code.startswith('ORDER_ALREADY_') for code in codes) or 'PREFERRED_INELIGIBLE' in codes:
        return 'REFUSE'
    if codes & {'DEADLINE_INFEASIBLE', 'CAPACITY_INFEASIBLE', 'NO_ELIGIBLE_WORKSHOP'}:
        return 'ESCALATE'
    return 'CLARIFY'


def evaluate(cases, *, mode, registry=None, model_key=None, interval=0):
    if not cases or len({case['id'] for case in cases}) != len(cases):
        raise ValueError('Provide nonempty cases with unique IDs.')
    records = []
    with tempfile.TemporaryDirectory(prefix='sweaterco-language-') as directory:
        for index, case in enumerate(cases):
            if index and interval:
                time.sleep(interval)
            db_path = str(Path(directory) / f'case-{index}.sqlite3')
            start = time.perf_counter()
            response, error = None, None
            try:
                response = chat.create(owner='language-evaluation', request_id=f'case-{index}',
                    db_path=db_path, as_of=date(2026, 4, 1), message=case['message'],
                    mode=mode, model_key=model_key, registry=registry)
                actual = behavior(response)
                if actual == 'SERVICE_ERROR':
                    error = 'MODEL_ERROR'
            except chat.ChatError as failed:
                actual, error = 'SERVICE_ERROR', failed.code
            latency = (time.perf_counter() - start) * 1000
            with Database(db_path) as db:
                writes = db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0]
            if writes or response and response.get('committed'):
                raise AssertionError('Intake evaluation unexpectedly committed production work.')
            draft = (response or {}).get('session', {}).get('task', {}).get('draft', {})
            expected_fields = case.get('expected_fields', {})
            records.append({**case, 'actual_behavior': actual,
                'behavior_match': actual == case['expected_behavior'], 'service_error': error,
                'latency_ms': round(latency, 3), 'draft': draft,
                'field_matches': {key: error is None and draft.get(key) == value
                                  for key, value in expected_fields.items()},
                'explanation': (response or {}).get('assistant_message', {}).get('content'),
                'explanation_review': None, 'response': response, 'production_rows_written': writes})
    latencies = sorted(row['latency_ms'] for row in records)
    fields = [match for row in records for match in row['field_matches'].values()]
    n = len(records)
    summary = {'checked_at': datetime.now(timezone.utc).isoformat(), 'mode': mode, 'model_key': model_key,
        'cases': n, 'service_successes': sum(row['service_error'] is None for row in records),
        'service_success_rate': sum(row['service_error'] is None for row in records) / n,
        'behavior_matches': sum(row['behavior_match'] for row in records),
        'behavior_accuracy_all_cases': sum(row['behavior_match'] for row in records) / n,
        'field_slots': len(fields), 'field_accuracy_all_labelled_slots': sum(fields) / len(fields) if fields else None,
        'latency_p50_ms': latencies[math.ceil(.5*n)-1], 'latency_p95_ms': latencies[math.ceil(.95*n)-1],
        'explanation_reviews_completed': 0, 'explanation_faithfulness': 'NOT_SCORED: independent human review required',
        'production_rows_written': 0,
        'notes': ['All service failures remain in the denominator.',
                  'ALLOCATE denotes an uncommitted recommendation.',
                  'Historical 30-case behavior labels predate the owner-scoped Chat v2 workflow.']}
    return summary, records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('offline', 'llm'), default='offline')
    parser.add_argument('--model-key')
    parser.add_argument('--cases', type=Path, help='JSONL: id, message, expected_behavior, optional expected_fields.')
    parser.add_argument('--interval-seconds', type=float, default=0)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'evaluation/live_results/chat-language')
    args = parser.parse_args()
    if not 0 <= args.interval_seconds <= 60:
        parser.error('--interval-seconds must be between 0 and 60')
    cases = ([json.loads(line) for line in args.cases.read_text().splitlines() if line.strip()]
             if args.cases else original_cases())
    registry = ModelRegistry(load_model_settings(mode=args.mode))
    try:
        selection = registry.resolve(args.mode, args.model_key)
        summary, records = evaluate(cases, mode=args.mode, registry=registry,
                                    model_key=selection.key if selection else None,
                                    interval=args.interval_seconds)
    finally:
        registry.close()
    summary['dataset'] = str(args.cases) if args.cases else 'original 30 development requests; provisional labels'
    summary['independent_holdout_claim'] = False
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (args.output_dir / 'cases.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in records))
    print(json.dumps(summary, indent=2))
    return 0 if summary['service_successes'] == len(cases) else 1


if __name__ == '__main__':
    raise SystemExit(main())
