#!/usr/bin/env python3
"""DSS5105 Track 2: clarification detection on the 30 original inbox requests.

Run from the repository root after copying this script and
clarification_gold_labels.csv into that root:
    uv run --locked python run_clarification_eval.py --backend offline
    uv run --locked --env-file .env python run_clarification_eval.py --backend deepseek
    uv run --locked --env-file .env python run_clarification_eval.py --backend llm

The script never changes your parser and never reports offline figures as LLM metrics.
"""
from __future__ import annotations
import argparse, csv, json, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from app.agent.parser import parse_with_telemetry

CLASSES=('ok','needs_clarification','invalid')

def safe_div(a,b):
    return a/b if b else 0.0

def run(args):
    goldfile=Path(args.gold)
    if not goldfile.is_absolute(): goldfile=ROOT/goldfile
    cases=list(csv.DictReader(goldfile.open(encoding='utf-8-sig',newline='')))
    if len(cases)!=30: raise ValueError(f'Expected exactly 30 requests; found {len(cases)}')
    results=[]
    for i,case in enumerate(cases,1):
        if i>1 and args.interval_seconds: time.sleep(args.interval_seconds)
        error=None;predicted=None;raw=None
        try:
            # Each group-chat item is ONE independent input; do not pass the Rxx label.
            outcome=parse_with_telemetry(case['request_text'],[],backend=args.backend)
            if outcome.parsed is not None:
                raw=outcome.parsed.to_dict()
                predicted=raw.get('parse_status')
            error=outcome.error
        except Exception as exc:
            error=f'{type(exc).__name__}: {exc}'
        if predicted not in CLASSES:
            predicted=None
        gold=case['gold_parse_status']
        item={**case,'predicted_status':predicted or 'PARSER_ERROR','match':int(predicted==gold),
              'parser_error':str(error or ''),'parsed_json':json.dumps(raw,ensure_ascii=False) if raw else ''}
        results.append(item)
        print(f"{case['request_id']}: gold={gold:20s} predicted={(predicted or 'PARSER_ERROR'):20s}" )
    tp=sum(r['gold_parse_status']=='needs_clarification' and r['predicted_status']=='needs_clarification' for r in results)
    fp=sum(r['gold_parse_status']!='needs_clarification' and r['predicted_status']=='needs_clarification' for r in results)
    fn=sum(r['gold_parse_status']=='needs_clarification' and r['predicted_status']!='needs_clarification' for r in results)
    tn=sum(r['gold_parse_status']!='needs_clarification' and r['predicted_status'] in ('ok','invalid') for r in results)
    failures=sum(r['predicted_status']=='PARSER_ERROR' for r in results)
    p=safe_div(tp,tp+fp);rec=safe_div(tp,tp+fn);f1=safe_div(2*p*rec,p+rec)
    matrix={g:{a:sum(r['gold_parse_status']==g and r['predicted_status']==a for r in results) for a in (*CLASSES,'PARSER_ERROR')} for g in CLASSES}
    metrics={'backend':args.backend,'dataset':'30 group-chat requests, 2026-04-01','n':len(results),
             'ground_truth':{c:sum(r['gold_parse_status']==c for r in results) for c in CLASSES},
             'tp':tp,'fp':fp,'fn':fn,'tn_excluding_failures':tn,'parser_errors':failures,
             'precision':p,'recall':rec,'f1':f1,
             'three_class_accuracy_all_requests':safe_div(sum(r['match'] for r in results),len(results)),
             'three_class_accuracy_on_responses':safe_div(sum(r['match'] for r in results),len(results)-failures),
             'confusion_matrix':matrix,
             'notes':['PARSER_ERROR is not a valid parse_status and is counted as a missed positive if gold=needs_clarification.',
                      'Do not interpret API quota/network failures as proof of semantic parsing failure.',
                      'Confirm borderline R16 label with a second annotator before final submission.']}
    out=Path(args.output_dir)
    if not out.is_absolute():out=ROOT/out
    out.mkdir(parents=True,exist_ok=True)
    with (out/f'clarification_predictions_{args.backend}.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(results[0].keys()));w.writeheader();w.writerows(results)
    (out/f'clarification_metrics_{args.backend}.json').write_text(json.dumps(metrics,indent=2,ensure_ascii=False),encoding='utf-8')
    print('\n=== RESULTS ===')
    for key in ('tp','fp','fn','tn_excluding_failures','parser_errors','precision','recall','f1','three_class_accuracy_all_requests'):
        print(key,':',round(metrics[key],4) if isinstance(metrics[key],float) else metrics[key])
    print('Files:',out)

if __name__=='__main__':
    a=argparse.ArgumentParser()
    a.add_argument('--backend',choices=['offline','llm','deepseek'],default='offline')
    a.add_argument('--gold',default='clarification_gold_labels.csv')
    a.add_argument('--output-dir',default='evaluation/results/clarification_detection')
    a.add_argument('--interval-seconds',type=float,default=0)
    args=a.parse_args()
    if not 0<=args.interval_seconds<=60: a.error('interval-seconds must be between 0 and 60')
    run(args)
