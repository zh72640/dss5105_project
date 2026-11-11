"""Rules and model interpretation share the same evidence-checked patch protocol."""
import json
import re
from datetime import date, timedelta
from typing import get_args
from app.schemas.chat import TurnInterpretation, PatchField
from app.schemas.parser_schema import OBJECTIVES
from app.services.intake.rule_parser import extract
from app.services.intake.normalization import PRODUCTS, order_ids, workshop_mentions, number
from app.services.allocation.preflight import issue
from app.services.intake.evidence import (date_mentions, product_evidence, category_evidence,
    literal_evidence, exclusion_operations, replaces_exclusions, clears_exclusions,
    pending_due_date, requests_recommendation, candidate_workshop_question)

from app.services.chat.alternative_acceptance import (
    is_offline_acceptance_request, offline_acceptance_interpretation, validate_acceptance_quote)

FIELDS = set(get_args(PatchField))
PENDING_DUE_DATE_QUESTION = 'The new due date is unconfirmed. Provide the new date or ask me to recommend a workshop without a due date.'
MULTIPLE_ORDER_IDS_QUESTION = 'Each allocation request supports one order. Which order should I handle first?'


def readable_ambiguity(reason):
    """Translate runtime clarification codes and deduplicate legacy reasons."""
    parts = [part.strip() for part in (reason or '').split(',') if part.strip()]
    labels = {'unconfirmed_due_date': PENDING_DUE_DATE_QUESTION,
              'multiple_order_ids': MULTIPLE_ORDER_IDS_QUESTION}
    return ', '.join(dict.fromkeys(labels.get(part, part) for part in parts)) or None


def clarify_multiple_orders(value, message):
    """Require selection before applying an ambiguous multi-order allocation turn.

    Existing requirements and unsupported blockers stay saved. No patches or
    alternative acceptance from this turn apply until one order is selected.
    Read-only and hypothetical interpretations keep their normal routing.
    """
    if (value.intent in ('allocate_request', 'modify_constraints', 'answer_clarification',
                         'select_workshop', 'unsupported_or_ambiguous') and not is_hypothetical(message) and
            len(order_ids(message, allow_short=True)) > 1):
        return TurnInterpretation(intent='answer_clarification', ambiguity_reason=MULTIPLE_ORDER_IDS_QUESTION,
                                  unsupported_constraints=value.unsupported_constraints)
    return value


def apply_due_date_context(value, message, context):
    """Attach evidenced pending-date policy and preserve unrelated ambiguities.

    A later instruction can authorize planning against an already pending date;
    a supplied date instead resolves it through the ordinary patch protocol.
    """
    supplied = any(p.field == 'due_date' and p.op == 'set' for p in value.patch_operations)
    source = context.get('field_sources', {}).get('due_date', {})
    old_pending = source.get('pending', False) or any(
        q.get('field') in ('due_date', 'message') and ('unconfirmed_due_date' in q.get('question', '') or
        q.get('question') == PENDING_DUE_DATE_QUESTION) for q in context.get('pending_questions', []))
    newly_pending = pending_due_date(message)
    proceed = requests_recommendation(message)
    value.due_date_pending = newly_pending or (old_pending and not supplied and proceed)
    value.recommend_without_due_date = value.due_date_pending and proceed
    reasons = [part.strip() for part in (value.ambiguity_reason or '').split(',') if part.strip()]
    if value.due_date_pending:
        reasons = [part for part in reasons if part not in ('unconfirmed_due_date', PENDING_DUE_DATE_QUESTION)]
        if not value.recommend_without_due_date:
            reasons.append(PENDING_DUE_DATE_QUESTION)
    value.ambiguity_reason = readable_ambiguity(','.join(reasons))
    return value


def ambiguity_field(reason, *, strict=False):
    """Scope questions; strict mode excludes legacy substring heuristics."""
    if reason == MULTIPLE_ORDER_IDS_QUESTION:
        return 'order_id'
    # A missing order reference is resolved by an evidenced order_id patch.
    # Full matching prevents a mixed or unrelated ambiguity being discarded.
    missing_order = (r"(?:no(?: specific)? order (?:id|identifier|reference)(?: (?:was |is )?provided)?|"
                     r"(?:the )?order (?:id|identifier|reference) (?:is )?(?:missing|not provided))"
                     r"(?:[.;]\s*(?:please )?(?:provide|specify) (?:the order (?:id|identifier|reference)|which order to allocate))?[.!]?")
    if re.fullmatch(missing_order, reason.strip(), re.I):
        return 'order_id'
    if re.fullmatch(r'The order (?:reference|ID|number) is needed to identify the usual '
                    rf"quantity for the (?:{'|'.join(PRODUCTS)})[.!]?", reason.strip(), re.I):
        return 'order_id'
    if strict:
        return 'message'
    return next((field for code, field in (('objective', 'objective'),
        ('workshop_limit', 'num_workshop_allowed'), ('pieces', 'pieces'),
        ('order_ids', 'order_id'), ('date', 'due_date')) if code in reason), 'message')


def pending_fields(context):
    """Return clarification fields, including a nonblocking pending-date notice."""
    fields = {item.get('field') for item in context.get('pending_questions') or [] if isinstance(item, dict)}
    if context.get('field_sources', {}).get('due_date', {}).get('pending'):
        fields.add('due_date')
    return fields


def is_hypothetical(message):
    """Recognize questions while allowing the supported faster-split instruction."""
    low = message.lower()
    if re.search(r'\u5982\u679c|\u5047\u5982|what if|^\s*if\b', low):
        return True
    faster_split = re.search(r'\bsplit\b[^.!?]*\bif (?:that|it|this) '
                             r'(?:gets? (?:it )?(?:back )?faster|(?:is|would be) faster)', low)
    return bool(re.search(r'\bif\b', low)) and not faster_split


class InterpretationValidationError(ValueError):
    def __init__(self, reason, **detail):
        super().__init__(reason)
        self.detail = {'reason': reason, **detail}



def rule_interpret(message, context):
    """Interpret an offline turn using current evidence and saved question context.

    Return patches or a read-only intent without retrieving registered order
    facts, selecting among multiple orders, or authorizing production writes.
    """
    if is_offline_acceptance_request(message):
        return offline_acceptance_interpretation(message, context.get('pending_alternatives', []))
    text = message.strip()
    low = text.lower().rstrip('.!\u3002\uff01')
    sequence = context['current_sequence']
    evidence = {'message_sequence': sequence, 'quote': text}
    output = {'intent': 'help_or_chat', 'patch_operations': [], 'unsupported_constraints': []}
    def patch(field, value=None, op='set'):
        output['patch_operations'].append(dict(op=op, field=field, value=value, evidence=evidence))
    if low in ('\u786e\u8ba4','\u786e\u8ba4\u63d0\u4ea4','\u63a5\u53d7\u65b9\u6848','\u786e\u8ba4\u5206\u914d','confirm','accept','accept allocation'):
        output['intent'] = 'confirm_allocation'
        return TurnInterpretation(**output)
    if re.search(r'^(?:new request|\u65b0\u8bf7\u6c42|\u65b0\u5efa(?:\u8bf7\u6c42|\u4f1a\u8bdd)|\u53e6\u4e00\u4e2a\u8ba2\u5355|another order)(?:\b|[\uff1a:\uff0c, ]|$)', low):
        output['intent'] = 'new_request'
        return TurnInterpretation(**output)
    if low in ('\u53d6\u6d88\u4efb\u52a1','\u53d6\u6d88\u8bf7\u6c42','cancel task','cancel request'):
        output['intent'] = 'cancel_task'
        return TurnInterpretation(**output)
    if low in ('\u62d2\u7edd\u63a8\u8350','reject recommendation','\u4e0d\u63a5\u53d7\u8fd9\u4e2a\u65b9\u6848'):
        output['intent'] = 'reject_recommendation'
        return TurnInterpretation(**output)
    if re.fullmatch(r'\u53d6\u6d88(?:\u9884\u7b97|\u7cbe\u786e\u62c6\u5206|\u8d28\u91cf\u9608\u503c)|(?:drop|remove) (?:budget|unsupported constraint)',low):
        output.update(intent='modify_constraints',answered_question_ids=['unsupported_constraint'])
        return TurnInterpretation(**output)
    if re.fullmatch(r'\u5ffd\u7565(?:\u4e0a\u4e00\u6761|\u521a\u624d\u90a3\u6761)(?:\u6d88\u606f|\u8981\u6c42)|ignore (?:last|previous) message',low):
        output.update(intent='modify_constraints',answered_question_ids=['AMBIGUOUS_MESSAGE'])
        return TurnInterpretation(**output)
    if re.fullmatch(r'\u53d6\u6d88\u5de5\u574a(?:\u8f6f)?\u504f\u597d|remove workshop preference',low):
        output.update(intent='modify_constraints',answered_question_ids=['soft_workshop_preference'])
        return TurnInterpretation(**output)
    if low in ('\u53d6\u6d88','cancel'):
        output.update(intent='unsupported_or_ambiguous', ambiguity_reason='Clarify whether to cancel the uncommitted request or reverse a committed production allocation.')
        return TurnInterpretation(**output)
    if re.search(r'\u64a4\u9500|\u64a4\u56de\u521a\u624d|undo|\u53d6\u6d88\u521a\u624d\u7684', low):
        fields = {'\u6570\u91cf': 'num_workshop_allowed', '\u5de5\u574a\u6570':'num_workshop_allowed', '\u76ee\u6807':'objective',
            '\u6392\u9664':'exclusion', '\u4ea4\u671f':'deadline_required', 'objective':'objective', 'count':'num_workshop_allowed', 'exclusion':'exclusion'}
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
    financial_topic = re.search(r'\b(?:quote[ds]?|invoice[ds]?|revenue)\b|\u9500\u552e\u62a5\u4ef7|\u53d1\u7968', low)
    financial_query = re.search(r'\b(?:what|how much|show|find|lookup|look up|tell me|retrieve)\b|^(?:quote|invoice)\b|\u67e5\u8be2|\u591a\u5c11', low)
    if financial_topic and financial_query:
        output.update(intent='unsupported_or_ambiguous',
                      ambiguity_reason='Sales quotes, invoices and revenue are outside the dispatch workflow. No allocation was requested or changed.')
        return TurnInterpretation(**output)
    hypothetical = is_hypothetical(low)
    querying = bool(re.search(r'\u4e3a\u4ec0\u4e48|\u4e3a\u4f55|\u600e\u6837|\u600e\u4e48\u6837|\u72b6\u6001|\u591a\u5c11|\u4ec0\u4e48\u65f6\u5019|\u80fd.*\u51c6\u65f6|\bwhy\b|\bstatus\b|any movement on|how much|when|on time\?', low))
    ids = order_ids(text, allow_short=True)
    previous_user=next((m['content'] for m in reversed(context['history']) if m['role']=='user'),'')
    previous_assistant=next((m['content'] for m in reversed(context['history']) if m['role']=='assistant'),'')
    # Supplying a short ID to a status question must not start an allocation.
    reference_only = re.fullmatch(
        r'(?:ORD(?:-\s*|\s+)\d{1,3}|O\d+|orders?(?:\s+(?:ids?|numbers?|nos?\.?))?\s*[:#]?\s*\d{1,3})[.!]?', text, re.I)
    if len(ids)==1 and reference_only and re.search(r'\u72b6\u6001|status',previous_user,re.I) and 'Provide a valid order ID' in previous_assistant:
        output.update(intent='query_order',referenced_order_id=ids[0])
        return TurnInterpretation(**output)
    parsed = extract(text, date.fromisoformat(context['business_date']))
    if len(ids) == 1:
        parsed['order_id'] = ids[0]
    # Vocabulary extensions only; database values are never extracted from an ID.
    if re.search(r'\u6210\u672c(?:\u8d8a\u4f4e|\u6700\u4f4e|\u4f18\u5148)|\u8d8a\u4fbf\u5b9c|\u6700\u4fbf\u5b9c|\u4fbf\u5b9c\u70b9|\u6210\u672c\u8d8a\u4f4e', low):
        parsed['objective'] = 'min_cost'
    if re.search(r'\u8d28\u91cf\u4f18\u5148|\u8d28\u91cf\u6700\u597d|\u7f3a\u9677\u6700\u5c11', low):
        parsed['objective'] = 'min_defects'
    if '\u5e73\u8861' in low:
        parsed['objective'] = 'hybrid'
    if re.search(r'\u4e0d\u8981\s*W', text, re.I):
        parsed['exclusion'] = list(set(parsed['exclusion']) | {wid for start,_,wid in workshop_mentions(text)
            if re.search(r'\u4e0d\u8981\s*$',text[max(0,start-10):start])})
        parsed['ambiguities'] = [a for a in parsed['ambiguities'] if a != 'unclear_workshop_constraint']
    limit = re.search(r'(?:\u6539\u6210|\u6700\u591a|\u4e0d\u8d85\u8fc7|\u81f3\u591a)\s*(-?\d+|[\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b])\s*(?:\u4e2a|\u5bb6)?\u5de5\u574a', text)
    if limit:
        words={'\u56db':4,'\u4e94':5,'\u516d':6,'\u4e03':7,'\u516b':8}
        parsed['num_workshop_allowed'] = words.get(limit[1]) if limit[1] in words else number(limit[1])
    if re.search(r'(?:at most|no more than|maximum|max)\s+(?:nine|ten|zero)\s+workshops?',low):
        parsed['ambiguities'].append('invalid_workshop_limit')
    if '\u5fc5\u987b\u51c6\u65f6' in text:
        parsed['deadline_required'] = True
    if re.search(r'\u5141\u8bb8\u8fdf\u4ea4|allow late', low):
        patch('deadline_required', False)
    for token, days in (('\u660e\u5929', 1), ('tomorrow', 1), ('\u4eca\u5929', 0), ('today', 0)):
        boundary = r'\b' if token.isascii() else ''
        cue = rf'(?:\u4ea4\u671f|\u622a\u6b62|due(?:\s+date)?|deadline|back\s+by|\bby\b)\s*{boundary}{re.escape(token)}{boundary}'
        if not re.search(cue, low):
            continue
        resolved = (date.fromisoformat(context['business_date']) + timedelta(days=days)).isoformat()
        if parsed['due_date'] and parsed['due_date'] != resolved:
            parsed['ambiguities'].append('conflicting_due_date')
            continue
        parsed['due_date'] = resolved
        parsed['ambiguities'] = [a for a in parsed['ambiguities'] if a != 'relative_due_date']
    if 'due_date' in pending_fields(context) and not parsed.get('due_date'):
        values = {value for value, _explicit in date_mentions(text, context['business_date'])}
        if len(values) == 1:
            parsed['due_date'] = values.pop()
    candidate_workshop = candidate_workshop_question(text, context.get('workshop_names'))
    if candidate_workshop:
        parsed['preferred_workshop'] = candidate_workshop
        parsed['ambiguities'] = [a for a in parsed['ambiguities'] if a != 'unclear_workshop_constraint']
    removed = set()
    for start, end, wid in workshop_mentions(text):
        prefix = text[max(0,start-28):start].lower()
        suffix = text[end:end+5]
        if re.search(r'\u6062\u590d|unexclude|do not exclude|don.t exclude|\u4e0d\u6392\u9664|\u53d6\u6d88\u6392\u9664', prefix):
            patch('exclusion', wid, 'remove')
            removed.add(wid)
        if re.search(r'\u4f18\u5148|prefer', prefix):
            output['unsupported_constraints'].append('soft_workshop_preference')
            parsed['ambiguities']=[a for a in parsed['ambiguities'] if a!='unclear_workshop_constraint']
        if re.search(r'\u53ea\u80fd|\u6307\u5b9a|\u5fc5\u987b\u4f7f\u7528',prefix):
            parsed['preferred_workshop']=wid
            parsed['ambiguities']=[a for a in parsed['ambiguities'] if a!='unclear_workshop_constraint']
    if removed:
        parsed['exclusion'] = [w for w in parsed['exclusion'] if w not in removed]
        parsed['ambiguities'] = [a for a in parsed['ambiguities'] if a not in ('negated_exclusion','unclear_workshop_constraint')]
    if re.search(r'\u6e05\u9664(?:\u5168\u90e8)?\u6392\u9664|clear exclusions', low):
        patch('exclusion', [], 'set')
    if re.search(r'\u53d6\u6d88\u6307\u5b9a\u5de5\u574a|clear preferred', low):
        patch('preferred_workshop', op='unset')
    if re.search(r'\u4f7f\u7528(?:\u8ba2\u5355)?\u767b\u8bb0(?:\u503c|\u4fe1\u606f)|use registered (?:details|values)', low):
        for field in ('customer','product','category','pieces','order_date','due_date'):
            patch(field, op='unset')
    unsupported = re.search(r'\u9884\u7b97|\bbudget\b|cost cap|exactly|\u7cbe\u786e|\u81f3\u5c11|at least|\u8d28\u91cf\u9608\u503c|defect.*(?:under|below)|\b(?:under|less than)\s*\d|\d+\s*%|within\s+\w+\s+days?|(?:\d+|[\u4e00\u4e8c\u4e24\u4e09\u56db\u4e94\u516d\u4e03\u516b])\u5929\u5185|(?:\u6210\u672c|\u8d39\u7528).*(?:\u4e0a\u9650|\u4e0d\u5f97\u8d85\u8fc7)|(?:\u4e0d\u8d85\u8fc7|\u6700\u591a\u82b1|\u4e0d\u5f97\u8d85\u8fc7)\s*\d+\s*(?:\u5143|\u7f8e\u5143|dollars|USD)', low)
    if unsupported:
        output['unsupported_constraints'].append('unsupported_constraint')
    if re.search(r'\u53d6\u6d88(?:\u9884\u7b97|\u7cbe\u786e\u62c6\u5206|\u8d28\u91cf\u9608\u503c)|(?:drop|remove) (?:budget|unsupported constraint)', low):
        output['unsupported_constraints'] = []
        output['answered_question_ids'] = ['unsupported_constraint']
    if hypothetical:
        output.update(intent='explain_recommendation', patch_operations=[], referenced_order_id=ids[0] if len(ids)==1 else None)
        return TurnInterpretation(**output)
    if querying and not candidate_workshop and not output['unsupported_constraints'] and not re.search(r'\u6539\u6210|\u6539\u4e3a|\u6392\u9664|exclude|\u4e0d\u8981|\u6700\u591a|\u5fc5\u987b|\u6210\u672c\u8d8a\u4f4e|\u5de5\u574a.*(?:\u72b6\u6001|\u4ea7\u80fd|\u8d39\u7528)|workshop.*(?:capacity|status|cost)', low):
        output.update(intent='query_order' if ids or re.search(r'\u72b6\u6001|status',low) else 'explain_recommendation',
            referenced_order_id=ids[0] if len(ids)==1 else None)
        if len(ids)>1:
            output.update(intent='unsupported_or_ambiguous',ambiguity_reason='Specify one order to query.')
        return TurnInterpretation(**output)
    if re.search(r'\u5de5\u574a.*(?:\u72b6\u6001|\u4ea7\u80fd|\u8d39\u7528)|workshop.*(?:capacity|status|cost)', low):
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
    if re.search(r'\u4e4b\u524d|\u521a\u624d|\u4e00\u6837|same|previous',low) and not output['patch_operations']:
        output.update(intent='unsupported_or_ambiguous',ambiguity_reason='Specify which earlier requirement or message should be reused.')
    elif (issues or output['unsupported_constraints'] or output['patch_operations'] or
          requests_recommendation(text) or re.search(r'\u5206\u914d|allocate|dispatch|\u91cd\u65b0\u63a8\u8350|\u91cd\u65b0\u8ba1\u7b97', low)):
        supplement = bool(pending_fields(context) & {item['field'] for item in output['patch_operations']})
        output['intent']='modify_constraints' if context['draft'].get('order_id') or supplement else 'allocate_request'
        if issues:
            output['ambiguity_reason']=','.join(sorted(set(issues)))
    elif text and low not in ('\u4f60\u597d','\u60a8\u597d','\u8c22\u8c22','hi','hello','help','\u5e2e\u52a9'):
        output.update(intent='unsupported_or_ambiguous',ambiguity_reason='Specify the order to query, revise, or allocate. Existing requirements were not changed.')
    if re.search(r'(?:\u4e0d\u8981|\u6392\u9664|exclude|avoid)\s*(?:\u5b83|\u8fd9\u4e2a\u5de5\u574a|that workshop)', low):
        rec=context['recommendation']
        parts=rec['result']['allocation'] if rec else []
        if len(parts)==1:
            patch('exclusion',parts[0]['workshop_id'],'add')
            output.update(intent='modify_constraints',ambiguity_reason=None)
        else:
            output.update(intent='unsupported_or_ambiguous',ambiguity_reason='Provide the workshop ID to exclude; the current reference is ambiguous.')
    if querying and output['patch_operations']:
        output['candidate_intents']=['query_order' if re.search(r'\u72b6\u6001|status',low) else 'explain_recommendation']
    value = clarify_multiple_orders(TurnInterpretation(**output), message)
    return apply_due_date_context(value, message, context)


def validate_interpretation(value, message, context):
    if value.intent == 'request_alternatives' and (value.patch_operations or value.accept_alternative or
            value.answered_question_ids or value.unsupported_constraints or value.ambiguity_reason):
        raise ValueError('ALTERNATIVES_QUERY_CANNOT_MODIFY_REQUIREMENTS')
    if value.intent == 'select_workshop' and not (value.accept_alternative or any(
            p.field == 'preferred_workshop' and p.op == 'set' for p in value.patch_operations)):
        raise ValueError('WORKSHOP_SELECTION_REQUIRED')
    if value.accept_alternative:
        validate_acceptance_quote(value.accept_alternative, message)
        from app.services.chat.alternative_acceptance import validate_workshop_reference
        validate_workshop_reference(value.accept_alternative, message,
            context.get('pending_alternatives', []), context.get('workshop_names'))
    if 'unsupported_constraint' in value.answered_question_ids and not re.search(r'\u53d6\u6d88(?:\u9884\u7b97|\u7cbe\u786e\u62c6\u5206|\u8d28\u91cf\u9608\u503c)|(?:drop|remove) (?:budget|unsupported constraint)',message,re.I):
        raise ValueError('UNGROUNDED_WITHDRAWAL')
    if 'AMBIGUOUS_MESSAGE' in value.answered_question_ids and not re.search(r'\u5ffd\u7565(?:\u4e0a\u4e00\u6761|\u521a\u624d\u90a3\u6761)(?:\u6d88\u606f|\u8981\u6c42)|ignore (?:last|previous) message',message,re.I):
        pending = [q for q in context.get('pending_questions', []) if q.get('code') == 'AMBIGUOUS_MESSAGE']
        supplied = {p.field for p in value.patch_operations if p.op == 'set'}
        # A fact answer is not a withdrawal. Require every issue covered by the
        # coarse code to be field-scoped; patches still pass evidence checks below.
        if ('order_id' not in supplied or not pending or any(
                q.get('field') not in ('message', 'order_id') or
                ambiguity_field(q['question'], strict=True) != 'order_id' for q in pending)):
            raise ValueError('UNGROUNDED_WITHDRAWAL')
    if 'soft_workshop_preference' in value.answered_question_ids and not re.search(r'\u53d6\u6d88\u5de5\u574a(?:\u8f6f)?\u504f\u597d|remove workshop preference',message,re.I):
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
    if evidence.message_sequence != context['current_sequence'] and not re.search(r'\u4e4b\u524d|\u521a\u624d|\u4e00\u6837|same|previous|\u539f\u6765',message,re.I):
        raise ValueError('STALE_EVIDENCE')
    field, val = operation.field, operation.value
    if operation.op in ('add', 'remove') and field != 'exclusion':
        raise ValueError('INVALID_PATCH_OPERATION')
    if operation.op=='undo':
        if not re.search(r'\u64a4\u9500|\u64a4\u56de|\u53d6\u6d88\u521a\u624d|\bundo\b',evidence.quote,re.I):
            raise ValueError('UNGROUNDED_UNDO')
        labels = {'objective':r'objective|\u76ee\u6807', 'exclusion':r'exclusion|\u6392\u9664',
                  'num_workshop_allowed':r'workshop (?:count|limit)|\u5de5\u574a\u6570|\u6570\u91cf',
                  'preferred_workshop':r'preferred|sole workshop|\u6307\u5b9a\u5de5\u574a',
                  'deadline_required':r'hard deadline|deadline constraint|\u4ea4\u671f\u8981\u6c42'}
        named = {name for name, pattern in labels.items() if re.search(pattern, evidence.quote, re.I)}
        if named and field not in named:
            raise ValueError('UNGROUNDED_UNDO_FIELD')
        if re.search(r"do not undo|don't undo|\u4e0d\u8981\u64a4\u9500|\u4e0d\u64a4\u9500", evidence.quote, re.I):
            raise ValueError('UNGROUNDED_UNDO')
        return
    if operation.op=='unset':
        if re.search(r"do not (?:clear|remove|unset)|don't (?:clear|remove|unset)|\u4e0d\u8981\u6e05\u9664|\u4e0d\u8981\u53d6\u6d88", evidence.quote, re.I):
            raise ValueError('UNGROUNDED_CLEAR')
        if not re.search(r'\u53d6\u6d88|\u6e05\u9664|\u79fb\u9664|\u767b\u8bb0|clear|remove|registered|unset',evidence.quote,re.I):
            raise ValueError('UNGROUNDED_CLEAR')
        labels={'deadline_required':r'\u4ea4\u671f|deadline|\u51c6\u65f6|late','preferred_workshop':r'\u6307\u5b9a|\u5de5\u574a|workshop|preferred',
            'exclusion':r'\u6392\u9664|exclusion','pieces':r'\u6570\u91cf|\u4ef6|pieces|quantity','customer':r'\u5ba2\u6237|customer',
            'product':r'\u4ea7\u54c1|product','category':r'\u54c1\u7c7b|category','order_date':r'\u65e5\u671f|date','due_date':r'\u4ea4\u671f|\u65e5\u671f|due|date',
            'objective':r'\u76ee\u6807|objective','num_workshop_allowed':r'\u5de5\u574a|workshop','order_id':r'\u8ba2\u5355|order'}
        registered=operation.field in ('customer','product','category','pieces','order_date','due_date') and re.search(r'\u767b\u8bb0|registered',evidence.quote,re.I)
        if not registered and not re.search(labels[field],evidence.quote,re.I):
            raise ValueError('UNGROUNDED_CLEAR_FIELD')
        return
    if field == 'exclusion':
        vals=val if isinstance(val,list) else [val]
        if any(not isinstance(w,str) or not re.fullmatch(r'W[1-9]\d*',w) for w in vals):
            raise ValueError('INVALID_EXCLUSION')
        if not vals:
            if operation.op != 'set' or not clears_exclusions(source):
                raise ValueError('UNGROUNDED_CLEAR')
        else:
            polarities = exclusion_operations(source, context.get('workshop_names'))
            rec = context.get('recommendation')
            if (rec and len(rec['result']['allocation']) == 1 and
                    re.search(r'(?:exclude|avoid|\u4e0d\u8981|\u6392\u9664)\s*(?:\u5b83|\u8fd9\u4e2a\u5de5\u574a|that workshop)', source, re.I) and
                    not re.search(r"do not exclude|don't exclude|\u4e0d\u6392\u9664|\u53d6\u6d88\u6392\u9664", source, re.I)):
                polarities.setdefault(rec['result']['allocation'][0]['workshop_id'], set()).add('add')
            expected = 'remove' if operation.op == 'remove' else 'add'
            if any(polarities.get(w) != {expected} for w in vals):
                raise ValueError('UNGROUNDED_EXCLUSION_OPERATION')
            prior = set(context.get('draft', {}).get('exclusion') or [])
            if operation.op == 'set' and prior - set(vals) and not replaces_exclusions(source):
                raise ValueError('EXCLUSION_REPLACEMENT_REQUIRES_AUTHORIZATION')
    elif field in ('pieces','num_workshop_allowed'):
        if type(val) is not int or val<=0 or (field=='num_workshop_allowed' and val>8):
            raise ValueError('INVALID_QUANTITY')
        numerals={int(n) for n in re.findall(r'(?<![A-Za-z\d.-])\d+(?![A-Za-z\d]|\.\d)',evidence.quote)}
        words={'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'\u4e00':1,'\u4e8c':2,'\u4e24':2,'\u4e09':3,'\u56db':4,'\u4e94':5,'\u516d':6,'\u4e03':7,'\u516b':8}
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
        quoted = {v for v, _ in date_mentions(evidence.quote, context['business_date'])}
        quoted.update(p.value for p in rule_interpret(evidence.quote, context).patch_operations if p.field == field)
        stated = {p.value for p in rule_interpret(source, context).patch_operations if p.field == field}
        if val not in quoted or val not in stated:
            raise ValueError('UNGROUNDED_DATE')
    if field == 'customer' and not literal_evidence(val, evidence.quote):
        raise ValueError('UNGROUNDED_CUSTOMER')
    if field == 'product' and not product_evidence(val, evidence.quote):
        raise ValueError('UNGROUNDED_PRODUCT')
    if field == 'category' and not category_evidence(val, evidence.quote):
        raise ValueError('UNGROUNDED_CATEGORY')
    if field=='order_id' and val not in order_ids(evidence.quote, allow_short=True):
        raise ValueError('UNGROUNDED_ORDER')
    if field in ('preferred_workshop','exclusion'):
        vals = val if isinstance(val,list) else [val]
        mentions={w[2] for w in workshop_mentions(evidence.quote, context.get('workshop_names'))}
        rec=context['recommendation']
        if rec and re.search(r'\u5b83|\u8fd9\u4e2a\u5de5\u574a|that workshop',evidence.quote,re.I) and len(rec['result']['allocation'])==1:
            mentions.add(rec['result']['allocation'][0]['workshop_id'])
        if not set(vals).issubset(mentions) and vals:
            raise ValueError('UNGROUNDED_WORKSHOP')
