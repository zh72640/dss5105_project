"""Field-level golden evaluation; offline metrics are never labelled LLM metrics."""
import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.agent.parser import parse_with_telemetry

CORE = ('order_id','objective','exclusion','num_workshop_allowed')


def normalize(value):
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, list):
        return sorted(normalize(v) for v in value)
    return value


def evaluate(backend='offline', interval_seconds=0):
    if not math.isfinite(interval_seconds) or not 0 <= interval_seconds <= 60:
        raise ValueError('interval_seconds must be between 0 and 60')
    cases = [json.loads(line) for line in (ROOT/'tests/parser_golden.jsonl').read_text().splitlines()]
    exact, normalized = Counter(), Counter()
    null_slots = hallucinations = passed = valid = first_valid = 0
    records = []
    for index, case in enumerate(cases):
        if index and interval_seconds:
            time.sleep(interval_seconds)
        out = parse_with_telemetry(case['message'], [], backend=backend)
        actual = out.parsed.to_dict() if out.parsed else {}
        expected = case['expected']
        valid += out.parsed is not None
        first_valid += bool(out.telemetry['attempts'] and out.telemetry['attempts'][0]['validated_output'] is not None)
        mismatches = {}
        for field, target in expected.items():
            value = actual.get(field)
            exact[field] += bool(actual) and value == target
            normalized[field] += bool(actual) and normalize(value) == normalize(target)
            if not actual or value != target:
                mismatches[field] = {'expected': target, 'actual': value}
            if target is None or (isinstance(target,list) and not target and field=='exclusion'):
                null_slots += 1
                hallucinations += bool(actual) and value not in (None, [])
        passed += not mismatches
        records.append({**case, 'actual': actual, 'mismatches': mismatches, 'error': out.error, **out.telemetry})
    n = len(cases)
    metrics = {'backend': backend, 'model': records[0]['model'], 'prompt_version': 'parser_v1',
               'golden_cases': n, 'edge_cases': sum(c['edge_case'] for c in cases),
               'first_attempt_structured_validity': first_valid/n, 'final_structured_validity': valid/n,
               'core_field_exact_match': sum(exact[f] for f in CORE)/(len(CORE)*n),
               'all_fields_exact_case_match': passed/n, 'passed_cases': passed,
               'field_exact_match': {f:exact[f]/n for f in cases[0]['expected']},
               'field_normalized_match': {f:normalized[f]/n for f in cases[0]['expected']},
               'missing_field_hallucination_rate': hallucinations/null_slots if null_slots else 0,
               'missing_field_slots': null_slots, 'hallucinated_slots': hallucinations,
               'mean_latency_ms': mean(r['latency_ms'] for r in records),
               'interval_seconds': interval_seconds,
               'error_counts': dict(Counter(r['error'] for r in records if r['error'])),
               'attempt_error_counts': dict(Counter(a['error'] for r in records for a in r['attempts'] if a['error'])),
               'cases_with_model_output': sum(any(a['raw_output'] is not None for a in r['attempts']) for r in records),
               'human_review_status': 'pending',
               'live_llm_validated': backend=='llm' and first_valid/n >= .98 and
                                     sum(exact[f] for f in CORE)/(len(CORE)*n) >= .90 and hallucinations == 0}
    return metrics, records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend',choices=['offline','llm'],default='offline')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'evaluation/results')
    parser.add_argument('--interval-seconds',type=float,default=0,help='Pause 0-60 seconds between evaluation cases')
    args=parser.parse_args(); metrics, records=evaluate(args.backend,args.interval_seconds)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/f'parser_{args.backend}_metrics.json').write_text(json.dumps(metrics,indent=2,ensure_ascii=False)+'\n')
    (args.output_dir/f'parser_{args.backend}_runs.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    print(json.dumps(metrics,indent=2,ensure_ascii=False))
    return 0 if metrics['first_attempt_structured_validity']>=.98 and metrics['core_field_exact_match']>=.9 and metrics['missing_field_hallucination_rate']==0 else 1


if __name__=='__main__':
    raise SystemExit(main())
