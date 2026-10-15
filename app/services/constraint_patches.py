"""Explicit field changes with reversible, source-linked events."""
from copy import deepcopy
from app.services.allocation_preflight import issue


def apply_interpretation(task, interpretation, sequence):
    out=deepcopy(task)
    changed=set()
    for p in interpretation.patch_operations:
        field=p.field
        old=deepcopy(out['draft'][field])
        if field=='order_id' and old and (p.value!=old or p.op in ('undo','unset')):
            out['issues'].append(issue('ORDER_SWITCH_REQUIRES_NEW_SESSION','order_id','This task is bound to another order. Create a new request for a different order.'))
            continue
        if p.op=='undo':
            event=next((c for c in reversed(out['changes']) if c['field']==field and not c.get('undone') and c.get('op')!='undo'),None)
            if event is None:
                out['issues'].append(issue('NOTHING_TO_UNDO',field,'There is no change to undo for this field.'))
                continue
            event['undone']=True
            val=deepcopy(event['before'])
        elif p.op=='unset':
            val=[] if field=='exclusion' else False if field=='deadline_required' else None
        elif p.op in ('add','remove'):
            if field!='exclusion':
                out['issues'].append(issue('INVALID_PATCH',field,'Only workshop exclusions support add or remove.'))
                continue
            values=p.value if isinstance(p.value,list) else [p.value]
            val=sorted(set(old)|set(values)) if p.op=='add' else [w for w in old if w not in values]
        else:
            val=deepcopy(p.value)
        changed.add(field)
        out['draft'][field]=val
        out['sources'][field]={'message_sequence':p.evidence.message_sequence,'quote':p.evidence.quote,'operation':p.op}
        out['changes'].append({'field':field,'before':old,'after':val,'sequence':sequence,'op':p.op})
    out['issues']=[p for p in out['issues'] if p['field'] not in changed and not
        (p['code'] in interpretation.answered_question_ids and p['code'] in ('unsupported_constraint','AMBIGUOUS_MESSAGE','soft_workshop_preference'))]
    if interpretation.ambiguity_reason:
        reason=interpretation.ambiguity_reason
        field=next((f for code,f in (('objective','objective'),('workshop_limit','num_workshop_allowed'),
            ('pieces','pieces'),('order_ids','order_id'),('date','due_date')) if code in reason),'message')
        out['issues'].append(issue('AMBIGUOUS_MESSAGE',field,reason))
    for constraint in interpretation.unsupported_constraints:
        labels={'unsupported_constraint':'budget cap, exact split, or quality threshold',
                'soft_workshop_preference':'soft workshop preference (the current preferred workshop is a hard constraint)'}
        out['issues'].append(issue(constraint,'unsupported','This requirement cannot be computed: '+labels.get(constraint,constraint)+'. Withdraw it or use an existing business workflow.'))
    out['draft']['parse_status']='ok' if out['draft']['order_id'] else 'needs_clarification'
    out['draft']['missing_fields']=[] if out['draft']['order_id'] else ['order_id']
    out['draft']['ambiguities']=[]
    return out
