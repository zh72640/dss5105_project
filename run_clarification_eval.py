#!/usr/bin/env python3
"""Evaluate current Chat v2 intake, separately from planning and explanation.

Each case gets a new temporary session. ``intake`` includes intent routing;
``extraction`` probes the extraction node directly and is NOT scored as routing.
Use --backend deepseek only for an explicitly labeled live provider run.
"""
from __future__ import annotations
import argparse, csv, json, sys, time, tempfile
from contextlib import contextmanager
from datetime import date
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from app.agent.allocation_graph import extract_fields
from app.agent.main_graph import identify
from app.agent.dynamic import AgentContext
from app.config.model_settings import load_model_settings
from app.db.database import Database
from app.llm.registry import ModelRegistry
from app.llm.errors import translate_error
from app.services.chat import service as chat
from app.services.chat.context import build_context
from app.services.chat.interpretation import rule_interpret, validate_interpretation
from app.prompts import get_registry


@contextmanager
def environment(backend):
    registry, spec = None, None
    if backend != 'offline':
        settings = load_model_settings(mode='llm', legacy_backend=backend)
        spec = next(s for s in settings.models if s.configured and
                    (backend != 'deepseek' or s.provider == 'deepseek'))
        registry = ModelRegistry(replace(settings, models=(spec,), default_model=spec.key))
    try:
        with tempfile.TemporaryDirectory(prefix='sweaterco-intake-eval-') as directory:
            yield str(Path(directory) / 'evaluation.sqlite3'), registry, spec
    finally:
        if registry:
            registry.close()


def evaluate(message, case_id, backend, layer, db, registry, spec):
    owner = 'intake-evaluation'
    sid = chat.create(owner=owner, request_id='create-'+case_id, db_path=db,
        as_of=date(2026, 4, 1), mode='offline' if backend == 'offline' else 'llm',
        **({'model_key': spec.key, 'registry': registry} if spec else {}))['session_id']
    session = chat.inspect(sid, owner=owner, db_path=db)
    with Database(db) as database:
        context = build_context(database.connection, session)
    if backend == 'offline':
        parsed = validate_interpretation(rule_interpret(message, context), message, context).model_dump()
        ambiguous = (parsed['intent'] == 'unsupported_or_ambiguous' and
                     'outside the dispatch workflow' not in (parsed.get('ambiguity_reason') or ''))
        route = 'allocation' if ambiguous or parsed['intent'] in ('allocate_request', 'modify_constraints', 'undo_change') else 'compat'
    else:
        agent = AgentContext(registry=registry, model_key=spec.key, owner=owner, db_path=db,
            session_id=sid, request_id='evaluate-'+case_id, user_message=message, as_of=date(2026,4,1))
        runtime = SimpleNamespace(context=agent)
        route = identify({}, runtime)['route'] if layer == 'intake' else 'allocation'
        if route == 'failed':
            return 'PARSER_ERROR', {'route': route}, 'INTENT_FAILED'
        if route == 'compat':
            return 'invalid', {'route': route}, None
        output = extract_fields({}, runtime)
        parsed = output.get('interpretation')
        if parsed is None:
            return 'PARSER_ERROR', output, 'EXTRACTION_REJECTED'
    if layer == 'intake' and route != 'allocation':
        return 'invalid', parsed, None
    order = any(p['field'] == 'order_id' and p.get('value') for p in parsed['patch_operations'])
    status = 'needs_clarification' if (not order or parsed.get('ambiguity_reason') or parsed.get('unsupported_constraints')) else 'ok'
    return status, parsed, None


CLASSES=('ok','needs_clarification','invalid')

def safe_div(a,b):
    return a/b if b else 0.0

def run(args):
    goldfile=Path(args.gold)
    if not goldfile.is_absolute(): goldfile=ROOT/goldfile
    cases=list(csv.DictReader(goldfile.open(encoding='utf-8-sig',newline='')))
    if len(cases)!=30: raise ValueError(f'Expected exactly 30 requests; found {len(cases)}')
    if args.case_ids:
        requested = set(args.case_ids)
        if requested - {case['request_id'] for case in cases}:
            raise ValueError('Unknown case ID in --case-ids')
        cases = [case for case in cases if case['request_id'] in requested]
    results=[]
    with environment(args.backend) as (db, registry, spec):
        provider_metadata = {'provider': spec.provider, 'model': spec.api_model_id} if spec else {'provider': 'offline', 'model': None}
        for i,case in enumerate(cases,1):
            if i>1 and args.interval_seconds: time.sleep(args.interval_seconds)
            started=time.monotonic()
            error=None;predicted=None;raw=None
            try:
                predicted, raw, error = evaluate(case['request_text'], case['request_id'], args.backend,
                    args.layer, db, registry, spec)
            except Exception as exc:
                error=translate_error(exc, spec.provider if spec else 'offline').details()
            if predicted not in CLASSES:
                predicted=None
            gold=case['gold_parse_status']
            item={**case,'predicted_status':predicted or 'PARSER_ERROR','match':int(predicted==gold),
                  'elapsed_seconds':round(time.monotonic()-started,3),
                  'parser_error':json.dumps(error) if error else '',
                  'parsed_json':json.dumps(raw,ensure_ascii=False) if raw else ''}
            results.append(item)
            print(f"{case['request_id']}: gold={gold:20s} predicted={(predicted or 'PARSER_ERROR'):20s}", flush=True)
        with Database(db) as database:
            assert database.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0] == 0
    tp=sum(r['gold_parse_status']=='needs_clarification' and r['predicted_status']=='needs_clarification' for r in results)
    fp=sum(r['gold_parse_status']!='needs_clarification' and r['predicted_status']=='needs_clarification' for r in results)
    fn=sum(r['gold_parse_status']=='needs_clarification' and r['predicted_status']!='needs_clarification' for r in results)
    tn=sum(r['gold_parse_status']!='needs_clarification' and r['predicted_status'] in ('ok','invalid') for r in results)
    failures=sum(r['predicted_status']=='PARSER_ERROR' for r in results)
    p=safe_div(tp,tp+fp);rec=safe_div(tp,tp+fn);f1=safe_div(2*p*rec,p+rec)
    matrix={g:{a:sum(r['gold_parse_status']==g and r['predicted_status']==a for r in results) for a in (*CLASSES,'PARSER_ERROR')} for g in CLASSES}
    metrics={'backend':args.backend, 'layer':args.layer, **provider_metadata,
             'prompt_version':get_registry().get('allocation.extract').version,
             'gold_comparison_valid': args.layer == 'intake','dataset':'30 group-chat requests, 2026-04-01','n':len(results),
             'ground_truth':{c:sum(r['gold_parse_status']==c for r in results) for c in CLASSES},
             'tp':tp,'fp':fp,'fn':fn,'tn_excluding_failures':tn,'parser_errors':failures,
             'precision':p,'recall':rec,'f1':f1,
             'three_class_accuracy_all_requests':safe_div(sum(r['match'] for r in results),len(results)),
             'three_class_accuracy_on_responses':safe_div(sum(r['match'] for r in results),len(results)-failures),
             'confusion_matrix':matrix,
             'notes':['PARSER_ERROR is not a valid parse_status and is counted as a missed positive if gold=needs_clarification.',
                      'Do not interpret API quota/network failures as proof of semantic parsing failure.',
                      'invalid means outside allocation intake, not that the overall app cannot answer queries.',
                      'No database enrichment, feasibility, explanation quality or commitment is measured.',
                      'Extraction-only gold comparisons are diagnostic and must not be reported as intake accuracy.']}
    if args.layer == 'extraction':
        # Queries were intentionally sent directly to the extraction node: a
        # routing gold label cannot score this experiment.
        metrics['accepted_extractions'] = len(results)-failures
        for key in ('precision','recall','f1','three_class_accuracy_all_requests','three_class_accuracy_on_responses','confusion_matrix'):
            metrics[key] = None
    out=Path(args.output_dir)
    if not out.is_absolute():out=ROOT/out
    out.mkdir(parents=True,exist_ok=True)
    with (out/f'clarification_predictions_{args.backend}.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(results[0].keys()));w.writeheader();w.writerows(results)
    (out/f'clarification_metrics_{args.backend}.json').write_text(json.dumps(metrics,indent=2,ensure_ascii=False),encoding='utf-8')
    print('\n=== RESULTS ===')
    for key in ('tp','fp','fn','tn_excluding_failures','parser_errors','precision','recall','f1','three_class_accuracy_all_requests'):
        print(key,':',round(metrics[key],4) if isinstance(metrics[key],float) else metrics[key])
    print('Gold comparison valid:', metrics['gold_comparison_valid'])
    print('Files:',out)
    return 1 if failures else 0

if __name__=='__main__':
    a=argparse.ArgumentParser()
    a.add_argument('--backend',choices=['offline','llm','deepseek'],default='offline')
    a.add_argument('--layer', choices=['intake','extraction'], default='intake')
    a.add_argument('--case-ids', nargs='+', help='Explicit subset for a separately recorded rerun')
    a.add_argument('--gold',default='clarification_gold_labels.csv')
    a.add_argument('--output-dir',default='evaluation/results/clarification_detection')
    a.add_argument('--interval-seconds',type=float,default=0)
    args=a.parse_args()
    if not 0<=args.interval_seconds<=60: a.error('interval-seconds must be between 0 and 60')
    raise SystemExit(run(args))
