"""Retain the 30 original Week 4 behaviour labels; report actual v0.1 behaviour."""
import csv
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.cli import request_text
from app.pipeline import process_request


def evaluate():
    with (ROOT/'evaluation/language_ground_truth.csv').open() as handle: labels=list(csv.DictReader(handle))
    records=[]
    for row in labels:
        result=process_request(request_text(row['request_id']),backend='offline',request_id='dispatch-'+row['request_id'])
        actual=result['result']['decision_status']
        records.append({'dataset_request_id':row['request_id'],'expected_behavior':row['expected_behavior'],
                        'actual_behavior':actual,'match':actual==row['expected_behavior'],'payload':result})
    return {'cases':len(records),'behavior_matches':sum(r['match'] for r in records),
            'scope':'behaviour only; each request uses a fresh database; original human labels remain provisional'},records


def main():
    summary,records=evaluate();out=ROOT/'evaluation/results';out.mkdir(parents=True,exist_ok=True)
    (out/'dispatch_behavior_metrics.json').write_text(json.dumps(summary,indent=2)+'\n')
    (out/'dispatch_runs.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    print(json.dumps(summary,indent=2))
    return 0 if summary['cases']==summary['behavior_matches'] else 1

if __name__=='__main__':raise SystemExit(main())
