"""Chat v2 session facade: create/inspect, offline turns, and explicit confirm.

LLM ``action=message`` turns delegate to ``app.services.chat.agent_turns`` then
``app.agent.runtime``. Offline mode uses ``app.offline.graph``.
Do not merge those paths; they keep separate graphs and completion rules.
"""
import json
import re
import uuid
from datetime import date
from copy import deepcopy
from app.db.database import Database, utc_now
from app.schemas.parser_schema import ParseResult
from app.schemas.chat import TurnInterpretation
from app.services.chat.context import build_context
from app.services.chat.constraint_patches import apply_interpretation
from app.offline.reply import solution_reply, clarification_reply, explain, conversational_reply
from app.offline.graph import GRAPH
from app.llm.errors import BackendError
from app.llm.errors import ModelSelectionError
from pydantic import ValidationError
from app.db import chat_repository as repository
from app.services.allocation import service as allocation
from app.services.allocation.preflight import digest, issue, preflight


class ChatError(ValueError):
    def __init__(self, code, message, status=409, *, details=None):
        super().__init__(message)
        self.code, self.status = code, status
        self.details = details


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def require_session(connection, sid, owner):
    session=repository.snapshot(connection,sid,owner)
    if session is None:
        raise ChatError('SESSION_NOT_FOUND','The session does not exist or is inaccessible.',404)
    return session


def replay(connection, key, fingerprint, owner):
    row=repository.replay_row(connection,key)
    if row is None:
        return None
    if row['fingerprint']!=fingerprint or row['owner_username']!=owner:
        raise ChatError('IDEMPOTENCY_CONFLICT','This request ID was used for different input.')
    return {**json.loads(row['response_json']),'replayed':True}


def insert_session(connection, owner, key, fingerprint, objective, mode, model_key, as_of, sid=None, title='New request'):
    sid=sid or uuid.uuid4().hex
    now=utc_now()
    draft=ParseResult(objective=objective).to_dict()
    repository.create_session(connection, session_id=sid, owner=owner, key=key,
        fingerprint=fingerprint, title=title, as_of=as_of, mode=mode, model_key=model_key,
        task_id=uuid.uuid4().hex, draft_json=encoded(draft), now=now)
    return sid


def create(*, owner, request_id, db_path, as_of, message='', objective='min_delay', mode=None, model_key=None, registry=None):
    fingerprint=digest([owner,request_id,message,objective,mode,model_key])
    with Database(db_path) as db:
        with db.transaction() as c:
            old=repository.creation_row(c,request_id)
            if old:
                if old['owner_username']!=owner or old['creation_fingerprint']!=fingerprint:
                    raise ChatError('IDEMPOTENCY_CONFLICT','This creation request ID was used for different input.')
                sid=old['session_id']
            else:
                if registry:
                    mode = mode or registry.settings.default_mode
                    selection=registry.resolve(mode,model_key,require_model=False)
                    model_key=selection.key if selection else None
                sid=insert_session(c,owner,request_id,fingerprint,objective,mode or 'offline',model_key,as_of,title=message or 'New request')
        if message.strip():
            first_key='chat-first-'+uuid.uuid5(uuid.NAMESPACE_URL,request_id).hex
            payload=turn(sid,owner=owner,request_id=first_key,expected_version=0,message=message,db_path=db_path,registry=registry)
            if old:
                payload['replayed']=True
            return payload
        session=require_session(db.connection,sid,owner)
        return {'session_id':sid,'session_version':session['version'],'session':session,'replayed':bool(old),'committed':False}


def inspect(sid, *, owner, db_path):
    with Database(db_path) as db:
        session=require_session(db.connection,sid,owner)
        refresh_validity(db.connection,session)
        return session


def refresh_validity(connection,session):
    """A read refresh can disable stale cards without mutating any stored record."""
    rec=session['recommendation']
    if not rec or rec['status']!='valid':
        return
    task=session['task']
    report,_,_,facts_hash=preflight(connection,task['draft'],date.fromisoformat(session['business_date']),task['issues'],task['sources'])
    if not report['ready_for_planning'] or facts_hash!=rec['facts_hash'] or task['task_version']!=rec['task_version']:
        rec['status']='superseded'
        rec['stale']=True
        task['state']='READY' if report['ready_for_planning'] else 'BLOCKED'
        report['blocking_issues'].append(issue('RECOMMENDATION_STALE','recommendation','Business facts changed. Recompute the recommendation before confirmation.'))
        task['report']=report


def reconcile_recommendation(connection, session):
    """Persist invalidation when a saved recommendation no longer matches business facts."""
    rec = session['recommendation']
    if not rec or rec['status'] != 'valid':
        return False
    task = session['task']
    report, _, _, facts_hash = preflight(connection, task['draft'],
        date.fromisoformat(session['business_date']), task['issues'], task['sources'])
    if (report['ready_for_planning'] and facts_hash == rec['facts_hash'] and
            task['task_version'] == rec['task_version']):
        return False
    repository.supersede_recommendation(connection,rec['recommendation_id'])
    task['state'] = 'READY' if report['ready_for_planning'] else 'BLOCKED'
    task['report'] = report
    save_task(connection, task)
    return True


def list_sessions(*, owner, db_path, after=0, limit=30):
    with Database(db_path) as db:
        rows=repository.session_page(db.connection,owner,after,limit)
        items=[dict(r) for r in rows[:limit]]
        return dict(items=items,next_cursor=items[-1]['cursor'] if len(rows)>limit else None)


def list_messages(sid, *, owner, db_path, after=0, limit=50):
    with Database(db_path) as db:
        require_session(db.connection,sid,owner)
        return repository.messages(db.connection,sid,after,limit)


def execution_trace(sid, *, owner, db_path, limit=100):
    """Expose owner-scoped, observable Agent events without model reasoning text."""
    with Database(db_path) as db:
        require_session(db.connection, sid, owner)
        calls = [dict(row) for row in repository.trace_calls(db.connection,sid,limit)]
        for call in calls:
            call["arguments"] = json.loads(call.pop("arguments_json"))
            call["result"] = json.loads(call.pop("result_json"))
        events = [dict(row) for row in repository.trace_events(db.connection,sid,limit)]
        for event in events:
            event["detail"] = json.loads(event.pop("detail_json"))
        return {"session_id": sid, "tool_calls": list(reversed(calls)), "events": list(reversed(events))}


def list_recommendations(*, owner, db_path, after=0, limit=50, status=None):
    with Database(db_path) as db:
        page=repository.recommendations(db.connection,owner,after,limit,None)
        for rec in page['items']:
            if rec['status']=='valid':
                session=require_session(db.connection,rec['session_id'],owner)
                refresh_validity(db.connection,session)
                if session['recommendation']['recommendation_id']==rec['recommendation_id'] and session['recommendation'].get('stale'):
                    rec.update(status='superseded',stale=True,task_state='BLOCKED')
        if status is not None:
            page['items']=[rec for rec in page['items'] if rec['status']==status]
        return page


def save_task(connection, task):
    return repository.save_task(connection, task)


def save_recommendation(connection, session, report, result, facts_hash, plan_hash):
    return repository.insert_recommendation(connection, session, result, facts_hash, plan_hash)


def already_confirmed(c, sid, rid, owner):
    if not rid:
        return None
    row=repository.confirmed_recommendation(c,sid,rid,owner)
    if row and row['status']=='confirmed':
        saved=repository.saved_turn_response(c,row['confirmation_turn_id'])
        return {**json.loads(saved['response_json']),'replayed':True,'already_executed':True}
    return None


def turn(sid, *, owner, request_id, expected_version, db_path, action='message', message='', recommendation_id=None, registry=None):
    with Database(db_path) as check_db:
        selected = require_session(check_db.connection, sid, owner)
        if selected['mode'] == 'llm':
            if action == 'message':
                from app.services.chat.agent_turns import turn as agent_turn
                return agent_turn(sid, owner=owner, request_id=request_id,
                    expected_version=expected_version, db_path=db_path, message=message, registry=registry)
            active = repository.has_running_agent(check_db.connection,sid)
            if active:
                raise ChatError('AGENT_RUN_IN_PROGRESS', 'Resume the interrupted request before another action.')
    if action=='message' and not message.strip():
        raise ChatError('INVALID_MESSAGE','Enter a message.',400)
    if action in ('confirm','archive') and message:
        raise ChatError('INVALID_MESSAGE','Confirmation and archive actions cannot include revisions. Send the revision first.',400)
    fingerprint=digest([sid,owner,request_id,expected_version,action,message,recommendation_id])
    with Database(db_path) as db:
        c=db.connection
        cached=replay(c,request_id,fingerprint,owner)
        if cached:
            return cached
        session=require_session(c,sid,owner)
        old=already_confirmed(c,sid,recommendation_id,owner) if action=='confirm' else None
        if old:
            return old
        if session['status']!='OPEN':
            raise ChatError('SESSION_ARCHIVED','The session is archived. Create a new request.')
        if session['version']!=expected_version:
            raise ChatError('SESSION_VERSION_CONFLICT','The session changed. Refresh and retry.')
        context=build_context(c,session)
        telemetry={}
        reply=None
        interpretation=None
        initial_interpretation=None
        if action in ('confirm','archive','new_request'):
            intent={'confirm':'confirm_allocation','archive':'cancel_task','new_request':'new_request'}[action]
            interpretation=TurnInterpretation(intent=intent)
        else:
            try:
                state=GRAPH.invoke(dict(message=message,context=context,mode=session['mode'],model_key=session['model_key'],registry=registry))
                interpretation=state['interpretation']
                telemetry=state['telemetry']
                if interpretation.intent=='help_or_chat':
                    reply,execution=conversational_reply(message,context,registry,session['mode'],session['model_key'])
                    if execution:
                        telemetry['reply_execution']=execution
            except Exception as error:
                if not isinstance(error,(BackendError,ModelSelectionError,ValidationError,ValueError)):
                    raise
                interpretation=TurnInterpretation(intent='unsupported_or_ambiguous')
                telemetry={'backend':session['mode'],'error':type(error).__name__}
        initial_message=''
        if interpretation.intent=='new_request':
            initial_message=re.sub(r'^(?:new request|新请求|新建(?:请求|会话)|另一个订单|another order)[：:，,\s]*','',message,flags=re.I).strip()
            if initial_message:
                fresh_context={'business_date':session['business_date'],'history':[],'current_sequence':1,
                    'draft':ParseResult().to_dict(),'field_sources':{},'recent_changes':[],'pending_questions':[],
                    'order_facts':{},'recommendation':None}
                try:
                    state=GRAPH.invoke(dict(message=initial_message,context=fresh_context,mode=session['mode'],model_key=session['model_key'],registry=registry))
                    initial_interpretation=state['interpretation']
                    telemetry['initial_interpretation']=state['telemetry']
                except (BackendError,ModelSelectionError,ValidationError,ValueError):
                    initial_interpretation=TurnInterpretation(intent='unsupported_or_ambiguous',ambiguity_reason='The new request needs clarification in its new session.')
        with db.transaction() as c:
            cached=replay(c,request_id,fingerprint,owner)
            if cached:
                return cached
            current=require_session(c,sid,owner)
            old=already_confirmed(c,sid,recommendation_id,owner) if action=='confirm' else None
            if old:
                return old
            if current['version']!=expected_version or current['status']!='OPEN':
                raise ChatError('SESSION_VERSION_CONFLICT','The session changed. Read its latest state.')
            session=current
            task=deepcopy(session['task'])
            prior_task_state=task['state']
            session['task']=task
            intent=interpretation.intent
            status=503 if telemetry.get('error') else 200
            if telemetry.get('error'):
                task['issues'].append(issue('MODEL_ERROR','message','The message could not be interpreted reliably. Retry or explicitly discard it; the prior recommendation cannot be confirmed.',message))
            elif intent not in ('confirm_allocation','query_order','query_workshop','explain_recommendation','help_or_chat'):
                task['issues']=[p for p in task['issues'] if p['code']!='MODEL_ERROR' or
                    (p.get('user_value')!=message and 'AMBIGUOUS_MESSAGE' not in interpretation.answered_question_ids)]
            committed=False
            result=None
            trace=None
            rec=session['recommendation']
            previous_session_id=None
            if intent=='new_request':
                previous_session_id=sid
                key='chat-new-'+uuid.uuid5(uuid.NAMESPACE_URL,request_id).hex
                new_sid=insert_session(c,owner,key,digest([owner,key]),'min_delay',session['mode'],session['model_key'],date.fromisoformat(session['business_date']))
                sid=new_sid
                expected_version=0
                session=require_session(c,sid,owner)
                task=deepcopy(session['task'])
                session['task']=task
                rec=None
                reply='A separate session was created. Enter the new order and requirements.'
                if initial_interpretation:
                    task=apply_interpretation(task,initial_interpretation,1)
                    task['task_version']=1
                    session['task']=task
                    report,result,trace,facts_hash,plan_hash=allocation.recommend(c,task['draft'],date.fromisoformat(session['business_date']),task['issues'],task['sources'])
                    task['report']=report
                    if report['ready_for_recommendation']:
                        rec=save_recommendation(c,session,report,result,facts_hash,plan_hash)
                        task['state']='RECOMMENDED'
                        reply=solution_reply(result,task['draft']['order_id'])
                    else:
                        task['state']='BLOCKED'
                        reply=clarification_reply(report)
            elif intent=='confirm_allocation':
                target=recommendation_id or (rec['recommendation_id'] if rec else None)
                if rec and rec['status']=='confirmed' and target==rec['recommendation_id']:
                    return already_confirmed(c,sid,target,owner)
                if not rec or rec['recommendation_id']!=target or rec['status']!='valid' or task['issues']:
                    raise ChatError('RECOMMENDATION_INVALID','There is no valid recommendation to confirm. Resolve blockers and recompute.')
                report,result,trace,facts_hash,plan_hash=allocation.recommend(c,task['draft'],date.fromisoformat(session['business_date']),task['issues'],task['sources'])
                task['report']=report
                if not report['ready_for_recommendation'] or facts_hash!=rec['facts_hash'] or plan_hash!=rec['plan_hash'] or task['task_version']!=rec['task_version']:
                    repository.supersede_recommendation(c,target)
                    task['state']='BLOCKED'
                    status=409
                    if report['ready_for_recommendation']:
                        rec=save_recommendation(c,session,report,result,facts_hash,plan_hash)
                        task['state']='RECOMMENDED'
                        reply='Business facts or the plan changed. Confirm this new recommendation.\n'+solution_reply(result,task['draft']['order_id'])
                    else:
                        reply=clarification_reply(report)
                else:
                    committed=True
                    task['state']='CONFIRMED'
                    reply=solution_reply(result,task['draft']['order_id'],True)
            elif intent=='query_order':
                oid=interpretation.referenced_order_id or task['draft']['order_id']
                row=repository.order_row(c,oid)
                if row:
                    order=dict(row)
                    reply=f"Order {oid} is {order['state']}; total {order['pieces']} pieces, completed {order['completed_pieces']}, remaining {order['pieces']-order['completed_pieces']}, due {order['due_date']}."
                else:
                    reply='Provide a valid order ID; I will not guess the order.'
            elif intent=='query_workshop':
                from app.services.intake.normalization import workshop_mentions
                ids={m[2] for m in workshop_mentions(message)}
                rows=repository.workshop_rows(c)
                reply='\n'.join(f"Workshop {w['workshop_id']} ({w['name']}): {w['status']}, capacity {w['capacity_pieces_per_day']} pieces/day, unit cost {w['cost_per_piece']}." for w in rows if not ids or w['workshop_id'] in ids) or 'Workshop not found.'
            elif intent=='explain_recommendation':
                reply=explain(session,message)
                if re.search(r'如果|假如|what if',message,re.I):
                    if re.search(r'允许迟交|allow late',message,re.I):
                        draft={**task['draft'],'deadline_required':False}
                        report,hypothesis,_,_,_=allocation.recommend(c,draft,date.fromisoformat(session['business_date']),task['issues'],task['sources'])
                        reply='Hypothetical comparison allowing lateness; current requirements and commitment are unchanged:\n'+(solution_reply(hypothesis,draft['order_id']) if report['ready_for_recommendation'] else clarification_reply(report))
                    else:
                        reply+=' State the hypothetical constraint to compare; current requirements remain unchanged.'
            elif intent=='help_or_chat':
                reply=reply or 'Provide an order ID or say what you want to query or change.'
            elif action=='archive':
                repository.archive_session(c,sid)
                repository.supersede_current(c,sid)
                if task['state']!='CONFIRMED':
                    task['state']='CANCELLED'
                reply='The session was archived. Its messages and committed result remain available.'
            elif task['state']=='CONFIRMED':
                reply='This task is committed and cannot be allocated again through a revision. Use production management or create a new request.'
            elif intent in ('cancel_task','reject_recommendation'):
                repository.supersede_current(c,sid)
                if action=='archive':
                    repository.archive_session(c,sid)
                task['state']='CANCELLED' if intent=='cancel_task' else 'BLOCKED'
                task['issues'].append(issue('TASK_CANCELLED' if intent=='cancel_task' else 'RECOMMENDATION_REJECTED','message','The task was cancelled. Create a new request.' if intent=='cancel_task' else 'The recommendation was rejected. State the revised requirements.'))
                reply=task['issues'][-1]['question']
            else:
                task=apply_interpretation(task,interpretation,context['current_sequence'])
                session['task']=task
                if task['state']=='CANCELLED':
                    task['issues'].append(issue('TASK_CANCELLED','message','The task was cancelled. Create a new request.'))
                else:
                    task['issues']=[p for p in task['issues'] if p['code']!='RECOMMENDATION_REJECTED' or not interpretation.patch_operations]
                task['task_version']+=1
                report,result,trace,facts_hash,plan_hash=allocation.recommend(c,task['draft'],date.fromisoformat(session['business_date']),task['issues'],task['sources'])
                task['report']=report
                repository.supersede_current(c,sid)
                if report['ready_for_recommendation']:
                    rec=save_recommendation(c,session,report,result,facts_hash,plan_hash)
                    task['state']='RECOMMENDED'
                    reply=solution_reply(result,task['draft']['order_id'])
                else:
                    task['state']='BLOCKED'
                    reply=clarification_reply(report)
            if task['state']=='RECOMMENDED' and rec:
                session['recommendation']=rec
                if 'explain_recommendation' in interpretation.candidate_intents or re.search(r'为什么|为何|\bwhy\b',message,re.I):
                    explanation=explain(session,message).split('\n',1)[-1]
                    reply+='\n'+explanation
                if 'query_order' in interpretation.candidate_intents and trace and trace.get('order'):
                    order=trace['order']
                    reply+=f"\nThe order is {order['state']} with {order['completed_pieces']} completed pieces."
            save_task(c,task)
            turn_id=uuid.uuid4().hex
            feedback_id=uuid.uuid4().hex
            now=utc_now()
            repository.start_turn(c,turn_id=turn_id,session_id=sid,request_id=request_id,
                fingerprint=fingerprint,expected_version=expected_version,action=action,
                input_json=encoded({'message':message,'recommendation_id':recommendation_id}),
                telemetry_json=encoded(telemetry),now=now)
            # The explicit column list above is deliberate when the contract grows.
            if committed:
                business_key='chat-commit-'+rec['recommendation_id']
                business_payload={'result':result,'trace':trace,'committed':True,'session_id':sid,'chat_turn_id':turn_id}
                class _Outcome:
                    pass
                outcome=_Outcome()
                outcome.parsed=ParseResult(**task['draft'])
                outcome.telemetry=telemetry
                allocation.record(c,business_key,digest([rec['recommendation_id'],rec['plan_hash']]),message or 'confirm',
                    outcome,business_payload)
                repository.assign_actor(c,business_key,owner)
                allocation.apply(c,business_key,result,trace,date.fromisoformat(session['business_date']))
            action_label={'confirm':'Confirm recommendation','archive':'Archive session','new_request':'New request'}.get(action,action)
            for offset,role,content,mid in ((1,'user',message or action_label,uuid.uuid4().hex),(2,'assistant',reply,feedback_id)):
                meta={'intent':intent,'recommendation_id':rec['recommendation_id'] if rec else None,'committed':committed}
                repository.insert_message(c,message_id=mid,session_id=sid,turn_id=turn_id,
                    sequence=expected_version*2+offset,role=role,content=content,metadata_json=encoded(meta),now=now)
            repository.increment_session(c,sid,now)
            response={'session_id':sid,'session_version':expected_version+1,'turn_id':turn_id,'intent':intent,'task_state':task['state'],
                'validation_report':task['report'],'assistant_message':{'message_id':feedback_id,'content':reply,'role':'assistant'},
                'feedback_message_id':feedback_id,'recommendation_id':rec['recommendation_id'] if rec else None,
                'cards':[],'suggested_actions':[],'committed':committed,'replayed':False,'http_status':status}
            if committed:
                response['committed_result']=result
                repository.confirm_recommendation(c,rec['recommendation_id'],turn_id,
                    business_key,feedback_id,encoded(result))
            response['session']=require_session(c,sid,owner)
            if response['session']['recommendation']:
                response['cards']=[response['session']['recommendation']]
            if previous_session_id:
                response['previous_session_id']=previous_session_id
            repository.save_turn_response(c,turn_id,encoded(response))
            if session['mode']=='llm' and action=='confirm':
                from app.db.agent_repository import record_event
                record_event(c,session_id=sid,request_id=request_id,
                    event_type='confirmation_committed' if committed else 'confirmation_stale',
                    detail={'recommendation_id':target,'session_version_before':expected_version,
                        'task_version':task['task_version'],'facts_hash':facts_hash,
                        'plan_hash':plan_hash,'business_request_id':business_key if committed else None,
                        'state_before':prior_task_state,'state_after':task['state'],
                        'committed':committed})
            return response
