"""Repeatable conversation corpus with input-defined oracles and explicit quality limits."""
import argparse
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from app.db.database import Database
from app.services.chat import service as chat
from app.llm.registry import ModelRegistry
from app.config.model_settings import load_model_settings


def corpus():
    cases=[]
    objectives={'min_delay':['Allocate fastest.','\u5e2e\u6211\u5206\u914d\uff0c\u6700\u5feb\u5b8c\u6210','Allocate urgently.','\u5206\u914d\uff0c\u4f18\u5148\u901f\u5ea6'],
        'min_cost':['Allocate cheapest.','\u5e2e\u6211\u5206\u914d\uff0c\u6210\u672c\u8d8a\u4f4e\u8d8a\u597d','Allocate at lowest cost.','\u5206\u914d\uff0c\u6700\u4f4e\u6210\u672c'],
        'min_defects':['Allocate lowest defects.','\u5e2e\u6211\u5206\u914d\uff0c\u8d28\u91cf\u4f18\u5148','Allocate best quality.','\u5206\u914d\uff0c\u6700\u4f4e\u7f3a\u9677'],
        'hybrid':['Allocate hybrid.','\u5e2e\u6211\u5206\u914d\uff0c\u5e73\u8861','Allocate balance speed and quality.','\u5206\u914d\uff0c\u65f6\u95f4\u8d28\u91cf\u5e73\u8861']}
    for objective,phrases in objectives.items():
        for phrase in phrases:
            for limit in (1,2,3,4):
                cases.append({'id':f'context-{len(cases)+1:02d}','messages':[phrase,'ORD-045','\u4e3a\u4ec0\u4e48\u9009\u8fd9\u4e2a\u5de5\u574a\uff1f',f'\u6700\u591a{limit}\u4e2a\u5de5\u574a\uff0c\u4e0d\u8981 W3'],
                    'expected':{'state':'RECOMMENDED','order_id':'ORD-045','objective':objective,'num_workshop_allowed':limit,'exclusion':['W3']},
                    'split':'candidate_holdout' if len(cases)%2 else 'development'})
    blockers=['Allocate cheapest.','Allocate ORD-999.','Allocate ORD-045 and ORD-109.',
        'Allocate ORD-045, 999 pieces.','Allocate ORD-045, -2 pieces.',
        'Allocate ORD-045; at most nine workshops.','Allocate ORD-045 due 2026-99-99.',
        'Allocate ORD-045 to W3; exclude W3.','Allocate ORD-045; exclude W99.',
        '\u5206\u914d ORD-045\uff0c\u4f18\u5148 W3','\u5206\u914d ORD-045\uff0c\u9884\u7b97100\u5143','Allocate ORD-045 exactly two workshops.',
        'Allocate ORD-045 cheapest and fastest.','Allocate ORD-045, not the cheapest.',
        'Allocate ORD-045; details to follow.','Allocate ORD-045 to W7.']
    for i,message in enumerate(blockers):
        cases.append({'id':f'blocker-{i+1:02d}','messages':[message],'expected':{'state':'BLOCKED'},'split':'development'})
    return cases


def evaluate(mode='offline',model_key=None):
    registry=ModelRegistry(load_model_settings(os.environ))
    registry.initialize()
    rows=[]
    try:
        for case in corpus():
            with tempfile.TemporaryDirectory() as directory:
                path=str(Path(directory)/'conversation.sqlite3')
                try:
                    payload=chat.create(owner='evaluation',request_id='create',db_path=path,as_of=date(2026,4,1),mode=mode,model_key=model_key,registry=registry)
                    for index,message in enumerate(case['messages']):
                        payload=chat.turn(payload['session_id'],owner='evaluation',request_id=f'turn-{index}',expected_version=payload['session_version'],message=message,db_path=path,registry=registry)
                    task=payload['session']['task'];expected=case['expected']
                    correct=task['state']==expected['state'] and all(task['draft'][key]==value for key,value in expected.items() if key!='state')
                    with Database(path) as db:
                        no_writes=db.connection.execute('SELECT COUNT(*) FROM working_order').fetchone()[0]==0
                    rows.append({'id':case['id'],'split':case['split'],'passed':correct and no_writes,'actual_state':task['state'],
                        'expected':expected,'actual_constraints':{k:task['draft'][k] for k in expected if k!='state'},
                        'committed':payload['committed'],'service_failed':payload.get('http_status',200)>=500})
                except Exception as error:
                    rows.append({'id':case['id'],'split':case['split'],'passed':False,'error_type':type(error).__name__,'service_failed':True})
    finally:
        registry.close()
    passed=sum(row['passed'] for row in rows)
    return {'mode':mode,'model_key':model_key,'cases':len(rows),'passed':passed,'failed':len(rows)-passed,
        'accuracy':passed/len(rows),'human_reviewed':False,'live_model_verified':mode=='llm' and not any(r.get('service_failed') for r in rows),
        'limitations':['Candidate holdout cases have not been independently reviewed; this is not a blind-test result.',
            'Offline checks do not establish arbitrary natural-language or live-model quality.'],'results':rows}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=('offline','llm'),default='offline')
    parser.add_argument('--model-key')
    parser.add_argument('--output',default='evaluation/results/conversation_verification.json')
    args=parser.parse_args()
    # Keep temporary SQLite files within the authorized project workspace on Windows.
    scratch=Path('runtime/chat-tests-temp').resolve();scratch.mkdir(parents=True,exist_ok=True)
    tempfile.tempdir=str(scratch)
    result=evaluate(args.mode,args.model_key)
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (output.parent/'conversation_cases.json').write_text(json.dumps(corpus(),ensure_ascii=True,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='results'},ensure_ascii=False))
    raise SystemExit(bool(result['failed']))


if __name__=='__main__':
    main()
