"""Repeatable conversation corpus with input-defined oracles and explicit quality limits."""
import argparse
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from app.db.database import Database
from app.services import chat
from app.core.models.registry import ModelRegistry
from app.config.model_settings import load_model_settings


def corpus():
    cases=[]
    objectives={'min_delay':['Allocate fastest.','帮我分配，最快完成','Allocate urgently.','分配，优先速度'],
        'min_cost':['Allocate cheapest.','帮我分配，成本越低越好','Allocate at lowest cost.','分配，最低成本'],
        'min_defects':['Allocate lowest defects.','帮我分配，质量优先','Allocate best quality.','分配，最低缺陷'],
        'hybrid':['Allocate hybrid.','帮我分配，平衡','Allocate balance speed and quality.','分配，时间质量平衡']}
    for objective,phrases in objectives.items():
        for phrase in phrases:
            for limit in (1,2,3,4):
                cases.append({'id':f'context-{len(cases)+1:02d}','messages':[phrase,'ORD-045','为什么选这个工坊？',f'最多{limit}个工坊，不要 W3'],
                    'expected':{'state':'RECOMMENDED','order_id':'ORD-045','objective':objective,'num_workshop_allowed':limit,'exclusion':['W3']},
                    'split':'candidate_holdout' if len(cases)%2 else 'development'})
    blockers=['Allocate cheapest.','Allocate ORD-999.','Allocate ORD-045 and ORD-109.',
        'Allocate ORD-045, 999 pieces.','Allocate ORD-045, -2 pieces.',
        'Allocate ORD-045; at most nine workshops.','Allocate ORD-045 due 2026-99-99.',
        'Allocate ORD-045 to W3; exclude W3.','Allocate ORD-045; exclude W99.',
        '分配 ORD-045，优先 W3','分配 ORD-045，预算100元','Allocate ORD-045 exactly two workshops.',
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
        'limitations':['候选 holdout 尚未经独立人工复核；本报告不是独立盲测成绩。',
            '离线测试不证明任意自然语言或在线模型质量。'],'results':rows}


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
    Path('evaluation/conversation_cases.json').write_text(json.dumps(corpus(),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='results'},ensure_ascii=False))
    raise SystemExit(bool(result['failed']))


if __name__=='__main__':
    main()
