"""Explicit field changes with reversible, source-linked events."""
from copy import deepcopy
import re
from app.services.allocation.preflight import issue
from app.services.chat.interpretation import readable_ambiguity, ambiguity_field as _ambiguity_field


def _resolved_legacy_assignment_issue(problem, interpretation):
    """Recognize the old direct-assignment refusals after a complete new request.

    Only the retired capability-denial wording is recoverable here. Genuine
    unsupported constraints and unrelated ambiguities remain user-resolved.
    """
    patches = {p.field: p for p in interpretation.patch_operations if p.op == 'set'}
    if (interpretation.intent not in ('allocate_request', 'modify_constraints') or
            interpretation.ambiguity_reason or interpretation.unsupported_constraints or
            not {'order_id', 'preferred_workshop'} <= patches.keys()):
        return False
    if problem['code'] == 'AMBIGUOUS_MESSAGE':
        return bool(re.fullmatch(
            r'This requests assigning an order directly to .+, but the allocation workflow '
            r'does not support direct workshop assignment\.|'
            r'This request is to assign an order to a workshop immediately, which cannot '
            r'be represented as an allocation constraint\.', problem.get('question', ''), re.I))
    if problem.get('field') != 'unsupported':
        return False
    legacy = re.fullmatch(r'Assign (ORD-\d{3}|O\d+) to (.+) immediately based on current availability\.',
                          problem['code'], re.I)
    return bool(legacy and legacy[1].upper() == patches['order_id'].value)


def apply_interpretation(task, interpretation, sequence):
    """Return a revised task with sources, reversible patches and scoped issues.

    Pending-date policy is already grounded by intake. Persist it across tools
    and turns without changing the authoritative registered order record.
    """
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
        if field == 'exclusion' and isinstance(val, str):
            # Evidence validation accepts a single workshop as well as a list.
            val = [val]
        changed.add(field)
        out['draft'][field]=val
        replacement = field == 'due_date' and p.op == 'set' and any(
            out['sources'].get(field, {}).get(key) for key in ('pending', 'replacement'))
        out['sources'][field]={'message_sequence':p.evidence.message_sequence,'quote':p.evidence.quote,'operation':p.op}
        if interpretation.accept_alternative:
            out['sources'][field]['alternative_id'] = interpretation.accept_alternative.alternative_id
        if replacement:
            out['sources'][field]['replacement'] = True
        out['changes'].append({'field':field,'before':old,'after':val,'sequence':sequence,'op':p.op})
    if interpretation.due_date_pending:
        # Keep the obsolete registered date out of every subsequent planning tool.
        out['draft']['due_date'] = None
        out['sources']['due_date'] = {'message_sequence': sequence, 'operation': 'pending',
            'pending': True, 'allow_without_due_date': interpretation.recommend_without_due_date}
        changed.add('due_date')
    def issue_field(p):
        # Also recover sessions saved before missing-reference messages were scoped.
        if p['code'] == 'AMBIGUOUS_MESSAGE' and p['field'] == 'message':
            return _ambiguity_field(p['question'])
        return p['field']
    out['issues']=[p for p in out['issues'] if not _resolved_legacy_assignment_issue(p, interpretation) and
        issue_field(p) not in changed and not
        (p['code'] in interpretation.answered_question_ids and p['code'] in ('unsupported_constraint','AMBIGUOUS_MESSAGE','soft_workshop_preference'))]
    if interpretation.ambiguity_reason:
        reason=readable_ambiguity(interpretation.ambiguity_reason)
        field=_ambiguity_field(reason)
        out['issues'].append(issue('AMBIGUOUS_MESSAGE',field,reason))
    for constraint in interpretation.unsupported_constraints:
        labels={'unsupported_constraint':'budget cap, exact split, or quality threshold',
                'soft_workshop_preference':'soft workshop preference (the current preferred workshop is a hard constraint)'}
        out['issues'].append(issue(constraint,'unsupported','This requirement cannot be computed: '+labels.get(constraint,constraint)+'. Withdraw it or use an existing business workflow.'))
    out['draft']['parse_status']='ok' if out['draft']['order_id'] else 'needs_clarification'
    out['draft']['missing_fields']=[] if out['draft']['order_id'] else ['order_id']
    out['draft']['ambiguities']=[]
    return out
