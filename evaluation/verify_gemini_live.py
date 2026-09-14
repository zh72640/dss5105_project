"""Explicit live Gemini smoke test; --full also runs the 60-case golden evaluation."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.agent.llm_client import GEMINI_MODEL, GEMINI_PROVIDER
from demos.week6_demo import run
from evaluation.evaluate_parser import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true', help='Also run 60 real LLM cases (up to 120 extra API calls)')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'evaluation/live_results')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = {'checked_at': datetime.now(timezone.utc).isoformat(), 'provider': GEMINI_PROVIDER,
               'model': GEMINI_MODEL, 'api_key_env': 'GEMINI_API_KEY', 'full_evaluation_requested': args.full,
               'status': 'NOT_RUN', 'live_llm_validated': False}
    if not os.getenv('GEMINI_API_KEY', '').strip():
        summary['reason'] = 'gemini_api_key_missing'
    else:
        demo = run('llm')
        (args.output_dir/'gemini_demo.json').write_text(json.dumps(demo, indent=2, ensure_ascii=False)+'\n')
        first = demo['first_request']
        summary.update(status='SMOKE_PASSED' if first['result']['success'] and demo['replay_is_idempotent'] else 'SMOKE_FAILED',
                       smoke_reason_codes=first['result']['reason_codes'],
                       parser_error=first['result']['message'] if first['result']['decision_status'] == 'ERROR' else None,
                       replay_is_idempotent=demo['replay_is_idempotent'])
        if args.full and summary['status'] == 'SMOKE_PASSED':
            metrics, records = evaluate('llm')
            (args.output_dir/'parser_llm_metrics.json').write_text(json.dumps(metrics, indent=2)+'\n')
            (args.output_dir/'parser_llm_runs.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in records))
            passed = (metrics['first_attempt_structured_validity'] >= .98 and
                      metrics['core_field_exact_match'] >= .90 and metrics['missing_field_hallucination_rate'] == 0)
            summary.update(status='ACCEPTANCE_PASSED' if passed else 'ACCEPTANCE_FAILED',
                           live_llm_validated=passed, golden_passed=metrics['passed_cases'])
    (args.output_dir/'gemini_live_status.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    # Summary never includes the key. Detailed model outputs stay in the explicit output directory.
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary['status'] in ('SMOKE_PASSED', 'ACCEPTANCE_PASSED') else 1


if __name__ == '__main__':
    raise SystemExit(main())
