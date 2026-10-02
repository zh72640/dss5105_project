"""Reproducible local verification and reviewable evidence, with nonzero failure exit."""
import io
import json
import platform
import subprocess
import sys
import unittest
from importlib.metadata import PackageNotFoundError, version
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from evaluation.evaluate_parser import evaluate
from evaluation.evaluate_dispatch import evaluate as evaluate_dispatch
from demos.week6_demo import run
from demos.lifecycle_demo import run as run_lifecycle
from demos.week5_mock import MESSAGES, handle_message
from app.agent.llm_client import GEMINI_MODEL, GEMINI_PROVIDER


def main():
    out=ROOT/'evaluation/results';out.mkdir(parents=True,exist_ok=True)
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (out/'test_results.txt').write_text(stream.getvalue())
    metrics,records=evaluate('offline')
    (out/'parser_offline_metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
    (out/'parser_offline_runs.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    demo=run('offline')
    (out/'week6_demo.json').write_text(json.dumps(demo,indent=2,ensure_ascii=False)+'\n')
    lifecycle = run_lifecycle()
    (out/'lifecycle_demo.json').write_text(json.dumps(lifecycle,indent=2,ensure_ascii=False)+'\n')
    (out/'week5_mock_demo.jsonl').write_text(''.join(json.dumps({'request_id':f'week5-demo-{i}',**handle_message(m)},ensure_ascii=False)+'\n' for i,m in enumerate(MESSAGES,1)))
    dispatch,dispatch_records=evaluate_dispatch()
    (out/'dispatch_behavior_metrics.json').write_text(json.dumps(dispatch,indent=2)+'\n')
    (out/'dispatch_runs.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in dispatch_records))
    sections=[]
    for label,flags in [('STANDARD',[]),('SHOCK',['--shock'])]:
        run_result=subprocess.run([sys.executable,str(ROOT/'harness/simulate.py'),*flags],capture_output=True,text=True,check=True)
        sections.append(f'[{label}]\n{run_result.stdout.strip()}\n')
    baseline_matches='\n'.join(sections)==(ROOT/'evaluation/baseline_results.txt').read_text()
    try:
        sdk_version = version('google-genai')
    except PackageNotFoundError:
        sdk_version = None
    summary={'checked_at':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),
             'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
             'tests_skipped':len(result.skipped),'google_genai_version':sdk_version,
             'golden_cases':metrics['golden_cases'],'golden_passed':metrics['passed_cases'],
             'demo_success':demo['first_request']['result']['success'],'idempotent_replay':demo['replay_is_idempotent'],
             'lifecycle_demo_verified':lifecycle['verified'],
             'lifecycle_queue_consistent':lifecycle['queue_consistent'],
             'lifecycle_foreign_keys_ok':lifecycle['foreign_keys_ok'],
             'original_dispatch_behavior_matches':dispatch['behavior_matches'],
             'official_simulator_matches_week4':baseline_matches,
             'llm_provider':GEMINI_PROVIDER,'llm_model':GEMINI_MODEL,
             'real_llm_call':'NOT_RUN: this verification command uses mocked SDK transport; run evaluation/verify_gemini_live.py for live evidence',
             'data_schema2_original':'NOT_PRESENT: implemented field mapping from Week 5/6 plans'}
    (out/'verification_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    if not result.wasSuccessful(): print(stream.getvalue())
    return 0 if result.wasSuccessful() and metrics['passed_cases']==60 and summary['demo_success'] and summary['idempotent_replay'] and lifecycle['verified'] and dispatch['behavior_matches']==30 and baseline_matches else 1


if __name__=='__main__':raise SystemExit(main())
