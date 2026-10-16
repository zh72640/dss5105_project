"""Rules and model interpretation share the same evidence-checked patch protocol."""
import json
import re
from datetime import date, timedelta
from typing import get_args
from app.schemas.chat import TurnInterpretation, PatchField
from app.schemas.parser_schema import OBJECTIVES
from app.services.intake.rule_parser import extract
from app.services.intake.normalization import order_ids, workshop_mentions, number
from app.services.allocation.preflight import issue

FIELDS = set(get_args(PatchField))


class InterpretationValidationError(ValueError):
    def __init__(self, reason, **detail):
        super().__init__(reason)
        self.detail = {'reason': reason, **detail}



def rule_interpret(message, context):
    text = message.strip()
    low = text.lower().rstrip('.!。！')
    sequence = context['current_sequence']
    evidence = {'message_sequence': sequence, 'quote': text}
    output = {'intent': 'help_or_chat', 'patch_operations': [], 'unsupported_constraints': []}
    def patch(field, value=None, op='set'):
        output['patch_operations'].append(dict(op=op, field=field, value=value, evidence=evidence))
    if low in ('确认','确认提交','接受方案','确认分配','confirm','accept','accept allocation'):
        output['intent'] = 'confirm_allocation'
        return TurnInterpretation(**output)
    if re.search(r'^(?:new request|新请求|新建(?:请求|会话)|另一个订单|another order)(?:\b|[：:，, ]|$)', low):
        output['intent'] = 'new_request'
        return TurnInterpretation(**output)
    if low in ('取消任务','取消请求','cancel task','cancel request'):
        output['intent'] = 'cancel_task'
        return TurnInterpretation(**output)
    if low in ('拒绝推荐','reject recommendation','不接受这个方案'):
        output['intent'] = 'reject_recommendation'
        return TurnInterpretation(**output)
    if re.fullmatch(r'取消(?:预算|精确拆分|质量阈值)|(?:drop|remove) (?:budget|unsupported constraint)',low):
        output.update(intent='modify_constraints',answered_question_ids=['unsupported_constraint'])
        return TurnInterpretation(**output)
    if re.fullmatch(r'忽略(?:上一条|刚才那条)(?:消息|要求)|ignore (?:last|previous) message',low):
        output.update(intent='modify_constraints',answered_question_ids=['AMBIGUOUS_MESSAGE'])
        return TurnInterpretation(**output)
    if re.fullmatch(r'取消工坊(?:软)?偏好|remove workshop preference',low):
        output.update(intent='modify_constraints',answered_question_ids=['soft_workshop_preference'])
        return TurnInterpretation(**output)
    if low in ('取消','cancel'):
        output.update(intent='unsupported_or_ambiguous', ambiguity_reason='Clarify whether to cancel the uncommitted request or reverse a committed production allocation.')
        return TurnInterpretation(**output)
    if re.search(r'撤销|撤回刚才|undo|取消刚才的', low):
        fields = {'数量': 'num_workshop_allowed', '工坊数':'num_workshop_allowed', '目标':'objective',
            '排除':'exclusion', '交期':'deadline_required', 'objective':'objective', 'count':'num_workshop_allowed', 'exclusion':'exclusion'}
        field = next((v for k,v in fields.items() if k in low), None)
        if not field:
            changes = context['recent_changes']
            if changes:
                last = changes[-1]['sequence']
                affected = {c['field'] for c in changes if c['sequence'] == last}
                if len(affected) == 1:
                    field = affected.pop()
        if field:
            patch(field, op='undo')
            output['intent'] = 'undo_change'
        else:
            output.update(intent='unsupported_or_ambiguous', ambiguity_reason='Specify which objective, workshop limit, exclusion, or deadline change to undo.')
        return TurnInterpretation(**output)
    hypothetical = bool(re.search(r'如果|假如|\bif\b|what if', low))
    querying = bool(re.search(r'为什么|为何|怎样|怎么样|状态|多少|什么时候|能.*准时|\bwhy\b|\bstatus\b|how much|when|on time\?', low))
    ids = order_ids(text)
    previous_user=next((m['content'] for m in reversed(context['history']) if m['role']=='user'),'')
    previous_assistant=next((m['content'] for m in reversed(context['history']) if m['role']=='assistant'),'')
    if len(ids)==1 and re.fullmatch(r'(?:ORD-\d{3}|O\d+)',text,re.I) and re.search(r'状态|status',previous_user,re.I) and 'Provide a valid order ID' in previous_assistant:
        output.update(intent='query_order',referenced_order_id=ids[0])
        return TurnInterpretation(**output)
    parsed = extract(text, date.fromisoformat(context['business_date']))
    # Vocabulary extensions only; database values are never extracted from an ID.
    if re.search(r'成本(?:越低|最低|优先)|越便宜|最便宜|便宜点|成本越低', low):
        parsed['objective'] = 'min_cost'
    if re.search(r'质量优先|质量最好|缺陷最少', low):
        parsed['objective'] = 'min_defects'
    if '平衡' in low:
        parsed['objective'] = 'hybrid'
    if re.search(r'不要\s*W', text, re.I):
        parsed['exclusion'] = list(set(parsed['exclusion']) | {wid for start,_,wid in workshop_mentions(text)
            if re.search(r'不要\s*$',text[max(0,start-10):start])})
        parsed['ambiguities'] = [a for a in parsed['ambiguities'] if a != 'unclear_workshop_constraint']
    limit = re.search(r'(?:改成|最多|不超过|至多)\s*(-?\d+|[一二两三四五六七八])\s*(?:个|家)?工坊', text)
    if limit:
        words={'四':4,'五':5,'六':6,'七':7,'八':8}
        parsed['num_workshop_allowed'] = words.get(limit[1]) if limit[1] in words else number(limit[1])
    if re.search(r'(?:at most|no more than|maximum|max)\s+(?:nine|ten|zero)\s+workshops?',low):
        parsed['ambiguities'].append('invalid_workshop_limit')
    if '必须准时' in text:
        parsed['deadline_required'] = True
    if re.search(r'允许迟交|allow late', low):
        patch('deadline_required', False)
    for token, days in (('明天',1),('tomorrow',1),('今天',0),('today',0)):
        if token in low and re.search(r'交期|截止|due|deadline|by', low):
            parsed['due_date'] = (date.fromisoformat(context['business_date'])+timedelta(days=days)).isoformat()
            parsed['ambiguities'] = [a for a in parsed['ambiguities'] if a != 'relative_due_date']
    removed = set()
    for start, end, wid in workshop_mentions(text):
        prefix = text[max(0,start-28):start].lower()
        suffix = text[end:end+5]
        if re.search(r'恢复|unexclude|do not exclude|don.t exclude|不排除|取消排除', prefix):
            patch('exclusion', wid, 'remove')
            removed.add(wid)
        if re.search(r'优先|prefer', prefix):
            output['unsupported_constraints'].append('soft_workshop_preference')
            parsed['ambiguities']=[a for a in parsed['ambiguities'] if a!='unclear_workshop_constraint']
        if re.search(r'只能|指定|必须使用',prefix):
            parsed['preferred_workshop']=wid
            parsed['ambiguities']=[a for a in parsed['ambiguities'] if a!='unclear_workshop_constraint']
    if removed:
        parsed['exclusion'] = [w for w in parsed['exclusion'] if w not in removed]
        parsed['ambiguities'] = [a for a in parsed['ambiguities'] if a not in ('negated_exclusion','unclear_workshop_constraint')]
    if re.search(r'清除(?:全部)?排除|clear exclusions', low):
        patch('exclusion', [], 'set')
    if re.search(r'取消指定工坊|clear preferred', low):
        patch('preferred_workshop', op='unset')
    if re.search(r'使用(?:订单)?登记(?:值|信息)|use registered (?:details|values)', low):
        for field in ('customer','product','category','pieces','order_date','due_date'):
            patch(field, op='unset')
    unsupported = re.search(r'预算|budget|cost cap|exactly|精确|至少|at least|质量阈值|defect.*(?:under|below)|\b(?:under|less than)\s*\d|\d+\s*%|within\s+\w+\s+days?|(?:\d+|[一二两三四五六七八])天内|(?:成本|费用).*(?:上限|不得超过)|(?:不超过|最多花|不得超过)\s*\d+\s*(?:元|美元|dollars|USD)', low)
    if unsupported:
        output['unsupported_constraints'].append('unsupported_constraint')
    if re.search(r'取消(?:预算|精确拆分|质量阈值)|(?:drop|remove) (?:budget|unsupported constraint)', low):
        output['unsupported_constraints'] = []
        output['answered_question_ids'] = ['unsupported_constraint']
    if hypothetical:
        output.update(intent='explain_recommendation', patch_operations=[], referenced_order_id=ids[0] if len(ids)==1 else None)
        return TurnInterpretation(**output)
    if querying and not output['unsupported_constraints'] and not re.search(r'改成|改为|排除|exclude|不要|最多|必须|成本越低|工坊.*(?:状态|产能|费用)|workshop.*(?:capacity|status|cost)', low):
        output.update(intent='query_order' if ids or re.search(r'状态|status',low) else 'explain_recommendation',
            referenced_order_id=ids[0] if len(ids)==1 else None)
        if len(ids)>1:
            output.update(intent='unsupported_or_ambiguous',ambiguity_reason='Specify one order to query.')
        return TurnInterpretation(**output)
    if re.search(r'工坊.*(?:状态|产能|费用)|workshop.*(?:capacity|status|cost)', low):
        output['intent']='query_workshop'
        return TurnInterpretation(**output)
    for field in FIELDS - {'exclusion','deadline_required'}:
        if parsed[field] is not None:
            value=parsed[field]
            if field in ('pieces','num_workshop_allowed') and (type(value) is not int or value<=0 or (field=='num_workshop_allowed' and value>8)):
                parsed['ambiguities'].append('invalid_'+field)
            else:
                patch(field,value)
    for wid in parsed['exclusion']:
        patch('exclusion',wid,'add')
    if parsed['deadline_required']:
        patch('deadline_required',True)
    issues = [a for a in parsed['ambiguities'] if a != 'unsupported_intent']
    if len(ids)>1:
        issues.append('multiple_order_ids')
    if re.search(r'之前|刚才|一样|same|previous',low) and not output['patch_operations']:
        output.update(intent='unsupported_or_ambiguous',ambiguity_reason='Specify which earlier requirement or message should be reused.')
    elif issues or output['unsupported_constraints'] or output['patch_operations'] or re.search(r'分配|allocate|dispatch|重新推荐|重新计算',low):
        output['intent']='modify_constraints' if context['draft'].get('order_id') else 'allocate_request'
        if issues:
            output['ambiguity_reason']=','.join(sorted(set(issues)))
    elif text and low not in ('你好','您好','谢谢','hi','hello','help','帮助'):
        output.update(intent='unsupported_or_ambiguous',ambiguity_reason='Specify the order to query, revise, or allocate. Existing requirements were not changed.')
    if re.search(r'它|这个工坊|that workshop',low) and re.search(r'不要|排除|exclude',low):
        rec=context['recommendation']
        parts=rec['result']['allocation'] if rec else []
        if len(parts)==1:
            patch('exclusion',parts[0]['workshop_id'],'add')
            output.update(intent='modify_constraints',ambiguity_reason=None)
        else:
            output.update(intent='unsupported_or_ambiguous',ambiguity_reason='Provide the workshop ID to exclude; the current reference is ambiguous.')
    if querying and output['patch_operations']:
        output['candidate_intents']=['query_order' if re.search(r'状态|status',low) else 'explain_recommendation']
    return TurnInterpretation(**output)


def validate_interpretation(value, message, context):
    if 'unsupported_constraint' in value.answered_question_ids and not re.search(r'取消(?:预算|精确拆分|质量阈值)|(?:drop|remove) (?:budget|unsupported constraint)',message,re.I):
        raise ValueError('UNGROUNDED_WITHDRAWAL')
    if 'AMBIGUOUS_MESSAGE' in value.answered_question_ids and not re.search(r'忽略(?:上一条|刚才那条)(?:消息|要求)|ignore (?:last|previous) message',message,re.I):
        raise ValueError('UNGROUNDED_WITHDRAWAL')
    if 'soft_workshop_preference' in value.answered_question_ids and not re.search(r'取消工坊(?:软)?偏好|remove workshop preference',message,re.I):
        raise ValueError('UNGROUNDED_WITHDRAWAL')
    for index, operation in enumerate(value.patch_operations):
        evidence = operation.evidence
        source = message if evidence.message_sequence == context['current_sequence'] else next(
            (m['content'] for m in context['history'] if m['role']=='user' and
             m['sequence']==evidence.message_sequence), None)
        try:
            _validate_operation(operation, message, context, source)
        except (ValueError, KeyError, TypeError) as error:
            raise InterpretationValidationError(str(error), error_type=type(error).__name__, field=operation.field,
                operation_index=index, operation=operation.model_dump(),
                expected_message_sequence=context['current_sequence'],
                actual_message_sequence=evidence.message_sequence,
                quote=evidence.quote, source_message=source, current_message=message) from error
    return value


def _validate_operation(operation, message, context, source):
    evidence = operation.evidence
    if operation.field not in FIELDS:
        raise ValueError('UNKNOWN_FIELD')
    if source is None:
        raise ValueError('EVIDENCE_SOURCE_NOT_FOUND')
    if evidence.quote not in source:
        raise ValueError('EVIDENCE_QUOTE_MISMATCH')
    if evidence.message_sequence != context['current_sequence'] and not re.search(r'之前|刚才|一样|same|previous|原来',message,re.I):
        raise ValueError('STALE_EVIDENCE')
    field, val = operation.field, operation.value
    if operation.op=='undo':
        if not re.search(r'撤销|撤回|取消刚才|\bundo\b',evidence.quote,re.I):
            raise ValueError('UNGROUNDED_UNDO')
        return
    if operation.op=='unset':
        if not re.search(r'取消|清除|移除|登记|clear|remove|registered|unset',evidence.quote,re.I):
            raise ValueError('UNGROUNDED_CLEAR')
        labels={'deadline_required':r'交期|deadline|准时|late','preferred_workshop':r'指定|工坊|workshop|preferred',
            'exclusion':r'排除|exclusion','pieces':r'数量|件|pieces|quantity','customer':r'客户|customer',
            'product':r'产品|product','category':r'品类|category','order_date':r'日期|date','due_date':r'交期|日期|due|date',
            'objective':r'目标|objective','num_workshop_allowed':r'工坊|workshop','order_id':r'订单|order'}
        registered=operation.field in ('customer','product','category','pieces','order_date','due_date') and re.search(r'登记|registered',evidence.quote,re.I)
        if not registered and not re.search(labels[field],evidence.quote,re.I):
            raise ValueError('UNGROUNDED_CLEAR_FIELD')
        return
    if field == 'exclusion':
        vals=val if isinstance(val,list) else [val]
        if any(not isinstance(w,str) or not re.fullmatch(r'W[1-9]\d*',w) for w in vals):
            raise ValueError('INVALID_EXCLUSION')
    elif field in ('pieces','num_workshop_allowed'):
        if type(val) is not int or val<=0 or (field=='num_workshop_allowed' and val>8):
            raise ValueError('INVALID_QUANTITY')
        numerals={int(n) for n in re.findall(r'(?<![A-Za-z\d.-])\d+(?![A-Za-z\d]|\.\d)',evidence.quote)}
        words={'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8}
        numerals.update(n for word,n in words.items() if re.search(r'\b'+word+r'\b',evidence.quote,re.I) if word.isascii())
        numerals.update(n for word,n in words.items() if not word.isascii() and word in evidence.quote)
        if val not in numerals:
            raise ValueError('UNGROUNDED_QUANTITY')
    elif field=='deadline_required':
        if type(val) is not bool:
            raise ValueError('INVALID_DEADLINE')
        stated={p.value for p in rule_interpret(evidence.quote,context).patch_operations if p.field==field}
        if val not in stated:
            raise ValueError('UNGROUNDED_DEADLINE')
    elif not isinstance(val,str) or not val.strip():
        raise ValueError('INVALID_VALUE')
    if field=='objective' and val not in OBJECTIVES:
        raise ValueError('INVALID_OBJECTIVE')
    if field=='objective':
        stated={p.value for p in rule_interpret(evidence.quote,context).patch_operations if p.field=='objective'}
        if val not in stated:
            raise ValueError('UNGROUNDED_OBJECTIVE')
    if field in ('order_date','due_date'):
        date.fromisoformat(val)
        if val not in evidence.quote:
            normalized={p.value for p in rule_interpret(evidence.quote,context).patch_operations if p.field==field}
            if val not in normalized:
                raise ValueError('UNGROUNDED_DATE')
    if field=='order_id' and val not in order_ids(evidence.quote, allow_short=True):
        raise ValueError('UNGROUNDED_ORDER')
    if field in ('preferred_workshop','exclusion'):
        vals = val if isinstance(val,list) else [val]
        mentions={w[2] for w in workshop_mentions(evidence.quote)}
        rec=context['recommendation']
        if rec and re.search(r'它|这个工坊|that workshop',evidence.quote,re.I) and len(rec['result']['allocation'])==1:
            mentions.add(rec['result']['allocation'][0]['workshop_id'])
        if not set(vals).issubset(mentions) and vals:
            raise ValueError('UNGROUNDED_WORKSHOP')
