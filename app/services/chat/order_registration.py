"""Conversational order drafts and explicit decisions; no allocation policy here."""
from datetime import date
import json
import re
from uuid import uuid4

from pydantic import ValidationError

from app.db.database import Database, utc_now
from app.db import chat_registration_repository as repo, chat_repository, agent_repository
from app.schemas.order_intake import ORDER_FIELDS, OrderFacts
from app.schemas.order_registration import RegistrationExtraction, RegistrationDecision
from app.services import order_intake
from app.services.allocation.preflight import digest
from app.services.intake import rule_parser
from app.services.intake.normalization import order_ids, PRODUCTS
from app.services.intake.evidence import category_evidence, product_evidence, literal_evidence, date_mentions

LABELS = {'order_id': 'order ID', 'customer': 'customer', 'product': 'product', 'category': 'category',
          'pieces': 'quantity', 'order_date': 'order date', 'due_date': 'due date'}


def active(task):
    return bool(task and task['status'] in ('COLLECTING', 'REVIEW') and
                not (task.get('review') or {}).get('decision'))


def starts_registration(message):
    """Conservative offline routing; LLM routing handles other natural phrasing."""
    return bool(re.search(r'\b(?:add|register|create|enter|record)\s+(?:(?:a|the|this|new)\s+)*order\b', message, re.I)
                and not re.search(r"\b(?:do not|don't|never)\s+(?:add|register|create|enter|record)\b", message, re.I))


def validate_extraction(candidate, message, business_date, draft=None):
    extraction = RegistrationExtraction.model_validate(candidate)
    if len(order_ids(message)) > 1:
        raise ValueError('Please register one order at a time and specify its order ID.')
    if extraction.intent == 'cancel':
        if extraction.patches or not re.match(r"^\s*(?:cancel|stop|discard|no\b|do not (?:add|create|update)|keep (?:the )?(?:existing|registered))", message, re.I):
            raise ValueError('Please say cancel registration explicitly if you want to stop.')
        return extraction
    ids = order_ids(message)
    if ids and (draft or {}).get('order_id') != ids[0] and not any(
            patch.field == 'order_id' and str(patch.value).strip().upper() == ids[0] for patch in extraction.patches):
        raise ValueError('Please restate the order ID; the reference in your message was omitted.')
    seen = set()
    defaults = dict(order_id='ORD-001', customer='Customer', product='Product', category='TOPS',
                    pieces=1, order_date='0001-01-01', due_date='9999-12-31')
    for patch in extraction.patches:
        field, value, quote = patch.field, patch.value, patch.quote
        if field in seen or quote not in message:
            raise ValueError(f'Please restate the {LABELS[field]}; its source could not be verified.')
        seen.add(field)
        if value is None:
            if not re.search(r'\b(?:clear|remove|unknown|unconfirmed|pending|not know)\b', quote, re.I):
                raise ValueError(f'Please explicitly state whether to clear the {LABELS[field]}.')
            continue
        value = OrderFacts.model_validate({**defaults, field: value}).model_dump()[field]
        if field == 'order_id':
            grounded = value in order_ids(quote)
        elif field in ('order_date', 'due_date'):
            grounded = (value, True) in date_mentions(quote, business_date)
            labeled = rule_parser.extract(quote, date.fromisoformat(business_date)).get(field)
            grounded = grounded and (not labeled or labeled == value)
        elif field == 'pieces':
            grounded = str(value) in re.findall(r'(?<![\w.\-])\d+(?![\w.]|\.\d)', quote)
        elif field == 'category':
            grounded = category_evidence(value, quote)
        elif field == 'product':
            grounded = product_evidence(value, quote)
        else:
            grounded = literal_evidence(value, quote)
        if not grounded:
            raise ValueError(f'Please restate the {LABELS[field]} explicitly' +
                             (' including its year.' if field.endswith('date') else '.'))
        patch.value = value
    return extraction


def offline_extract(message, session):
    if active(session.get('order_registration')) and re.fullmatch(
            r'\s*(?:cancel(?: (?:order )?registration)?|stop|discard|no(?:,? (?:keep|do not).*?)?|keep (?:the )?(?:existing|registered) values)[.!]?\s*', message, re.I):
        return RegistrationExtraction(intent='cancel')
    parsed = rule_parser.extract(message, date.fromisoformat(session['business_date']))
    if any(item.startswith('conflicting_') or item in ('invalid_date', 'relative_due_date', 'multiple_order_ids')
           for item in parsed.get('ambiguities', [])):
        return RegistrationExtraction(ambiguity='Please clarify conflicting quantities, products or dates.')
    patches = [{'field': key, 'value': parsed[key], 'quote': message} for key in ORDER_FIELDS if parsed.get(key) is not None]
    quantity = re.search(r'\b(\d+)\s+(?:knitted\s+)?(?:' + '|'.join(PRODUCTS) + r')\b', message, re.I)
    if not parsed.get('pieces') and quantity:
        patches.append({'field': 'pieces', 'value': int(quantity[1]), 'quote': quantity[0]})
    # Explicit labels also cover products outside the bundled product vocabulary.
    for field in ('customer', 'product', 'category', 'pieces'):
        match = re.search(r'\b' + field + r'\s*[:=]\s*([^;\n,]+)', message, re.I)
        if match:
            value = match[1].strip()
            if field == 'pieces' and value.isdigit():
                value = int(value)
            patches = [p for p in patches if p['field'] != field] + [{'field': field, 'value': value, 'quote': match[0]}]
    return validate_extraction({'patches': patches}, message, session['business_date'],
                               (session.get('order_registration') or {}).get('draft'))


def _issue(question):
    return {'code': 'ORDER_REGISTRATION_DETAILS', 'field': 'order', 'severity': 'blocking', 'question': question}


def reply(task):
    review = task.get('review')
    if review and review.get('decision'):
        result = review['decision']
        return result['message'] + (f" To allocate this order, send: Allocate {review['order_id']}." if result['applied'] else '')
    if task['status'] == 'CANCELLED':
        return 'Order registration cancelled. No order was created or changed. The decision is retained in the audit history.'
    if task['issues']:
        return ' '.join(item['question'] for item in task['issues'])
    if not review:
        return 'Provide the order ID, customer, product, category, quantity, order date and due date to register an order.'
    if review['match'] == 'identical':
        return f"Order {review['order_id']} is already registered with the same details. No duplicate was created. To allocate it, send: Allocate {review['order_id']}."
    if review['match'] == 'missing':
        return f"Order {review['order_id']} was not found. Review its details and use Confirm new order to add it, or Do not add order to decline. Nothing has been created yet."
    return f"Order {review['order_id']} already exists with different details. Verify each difference and retype its ID to approve changes, or choose Keep registered values. Both decisions are recorded. " + (review['update_blocker'] or '')


def task_result(task):
    return {'task_id': task['task_id'], 'task_type': 'order_registration',
            'status': 'completed' if task['status'] in ('COMPLETED', 'CANCELLED') else 'waiting_user',
            'result': {'registration': task, 'question': reply(task)}, 'issues': task['issues']}


def _reject_review(connection, task, owner, request_id, reason):
    review = task.get('review')
    if review and review['match'] != 'identical' and not review.get('decision'):
        order_intake.decide_in_transaction(connection, review['review_id'], {
            'request_id': 'registration-reject-' + digest([request_id, review['review_id']]), 'action': 'reject',
            'expected_version': review['expected_version'], 'reason': reason[:2000]}, actor=owner)


def prepare_in_transaction(connection, session, *, owner, request_id, message, extraction):
    from app.services.chat.service import ChatError
    fingerprint = digest([session['session_id'], owner, message])
    saved = repo.step(connection, request_id)
    if saved:
        if saved['session_id'] != session['session_id'] or saved['fingerprint'] != fingerprint:
            raise ChatError('IDEMPOTENCY_CONFLICT', 'This registration request ID was used for different input.')
        return json.loads(saved['result_json'])
    previous = session.get('order_registration')
    task = previous if active(previous) else dict(session_id=session['session_id'], task_id=str(uuid4()),
        status='COLLECTING', draft={}, issues=[], review_id=None, review=None)
    task['issues'] = []
    problem = None
    try:
        extraction = validate_extraction(extraction, message, session['business_date'], task['draft'])
    except (ValueError, ValidationError) as error:
        problem = str(error) if not isinstance(error, ValidationError) else 'Please check the supplied field values, dates and positive whole-number quantity.'
        extraction = RegistrationExtraction(ambiguity=problem)
    if extraction.intent == 'cancel':
        _reject_review(connection, task, owner, request_id, message)
        task['status'] = 'CANCELLED'
    elif extraction.ambiguity:
        task['issues'] = [_issue(problem or 'Please restate any ambiguous order details. No order has been created or changed.')]
        _reject_review(connection, task, owner, request_id, 'Review withdrawn because the latest registration input needs clarification.')
        task.update(status='COLLECTING', review=None, review_id=None)
    else:
        draft = dict(task['draft'])
        for patch in extraction.patches:
            if patch.value is None:
                draft.pop(patch.field, None)
            else:
                draft[patch.field] = patch.value
        if draft != task['draft']:
            _reject_review(connection, task, owner, request_id, 'Superseded by revised registration details: ' + message)
            task.update(draft=draft, status='COLLECTING', review_id=None, review=None)
        missing = [LABELS[field] for field in ORDER_FIELDS if field not in draft]
        if missing:
            task['issues'] = [_issue('Please provide: ' + ', '.join(missing) + '. Use dates with a year, such as 2026-11-25.')]
        elif not task.get('review'):
            try:
                facts = OrderFacts.model_validate(draft)
            except ValidationError:
                task['issues'] = [_issue('Check the dates and quantity. Due date must not precede order date; quantity must be a positive whole number.')]
            else:
                review = order_intake.check_in_transaction(connection, {
                    'request_id': 'chat-registration-' + digest([request_id, task['task_id']]),
                    'order': facts.model_dump()}, actor=owner)
                task.update(review_id=review['review_id'], review=review,
                            status='COMPLETED' if review['match'] == 'identical' else 'REVIEW')
    # A registration task cannot leave an unrelated allocation card actionable.
    chat_repository.supersede_current(connection, session['session_id'])
    repo.save(connection, task)
    task = repo.get(connection, session['session_id'])
    result = task_result(task)
    repo.save_step(connection, request_id, session['session_id'], fingerprint, result)
    return result


def prepare(sid, *, owner, request_id, message, expected_version, db_path, extraction):
    from app.services.chat.service import require_session, ChatError
    with Database(db_path) as db, db.transaction() as connection:
        session = require_session(connection, sid, owner)
        if session['status'] != 'OPEN' or session['version'] != expected_version:
            raise ChatError('SESSION_VERSION_CONFLICT', 'Refresh this request before continuing registration.')
        return prepare_in_transaction(connection, session, owner=owner, request_id=request_id,
                                      message=message, extraction=extraction)


def archive_in_transaction(connection, session, *, owner, request_id):
    task = session.get('order_registration')
    if active(task):
        _reject_review(connection, task, owner, request_id, 'Registration declined when the request was archived.')
        task.update(status='CANCELLED', issues=[])
        repo.save(connection, task)


def _finish(connection, session, *, owner, request_id, fingerprint, action, message, payload, status=200):
    from app.services.chat.service import require_session, encoded
    sid, version, now = session['session_id'], session['version'], utc_now()
    task = repo.get(connection, sid)
    text = reply(task)
    turn_id, feedback_id = str(uuid4()), str(uuid4())
    chat_repository.start_turn(connection, turn_id=turn_id, session_id=sid, request_id=request_id,
        fingerprint=fingerprint, expected_version=version, action=action, input_json=encoded(payload),
        telemetry_json=encoded({'workflow': 'order_registration', 'backend': 'deterministic'}), now=now)
    decision = (task.get('review') or {}).get('decision')
    metadata = encoded({'intent': 'order_registration', 'registration_status': task['status'],
                        'order_review_id': task['review_id'], 'order_decision_outcome': decision['outcome'] if decision else None})
    for offset, role, content, mid in ((1, 'user', message, str(uuid4())), (2, 'assistant', text, feedback_id)):
        chat_repository.insert_message(connection, message_id=mid, session_id=sid, turn_id=turn_id,
            sequence=version*2+offset, role=role, content=content, metadata_json=metadata, now=now)
    chat_repository.increment_session(connection, sid, now)
    response = {'session_id': sid, 'session_version': version+1, 'turn_id': turn_id, 'intent': 'order_registration',
        'assistant_message': {'message_id': feedback_id, 'role': 'assistant', 'content': text},
        'order_registration': task, 'session': require_session(connection, sid, owner),
        'committed': False, 'replayed': False, 'http_status': status}
    chat_repository.save_turn_response(connection, turn_id, encoded(response))
    return response


def turn(sid, *, owner, request_id, expected_version, db_path, message='', decision=None):
    from app.services.chat.service import require_session, replay, ChatError
    from app.services.chat.request_runs import execution_claim
    if decision is None and not message.strip():
        raise ChatError('INVALID_MESSAGE', 'Enter a message.', 400)
    action = 'order_decision' if decision is not None else 'message'
    fingerprint = digest([sid, owner, request_id, expected_version, action, message, None] +
                         ([decision] if decision is not None else []))
    with Database(db_path) as db:
        require_session(db.connection, sid, owner)
    with execution_claim(db_path, sid), Database(db_path) as db, db.transaction() as connection:
        cached = replay(connection, request_id, fingerprint, owner)
        if cached:
            return cached
        session = require_session(connection, sid, owner)
        if session['status'] != 'OPEN' or session['version'] != expected_version:
            raise ChatError('SESSION_VERSION_CONFLICT', 'Refresh the request before continuing.')
        if agent_repository.running_request(connection, sid):
            raise ChatError('AGENT_RUN_IN_PROGRESS', 'Resume or end the pending message first.')
        status = 200
        if decision is not None:
            if message:
                raise ChatError('INVALID_MESSAGE', 'Send revisions separately before deciding.', 400)
            try:
                body = RegistrationDecision.model_validate(decision)
                data = body.intake_input('chat-order-decision-' + digest([request_id]))
            except ValidationError as error:
                raise ChatError('INVALID_FIELDS', 'Review the decision fields and give a reason.', 400) from error
            task = session.get('order_registration')
            if not task or task['review_id'] != body.review_id or task['status'] != 'REVIEW' or task['issues']:
                raise ChatError('ORDER_REVIEW_CHANGED', 'This order review is no longer current. Refresh the request.')
            try:
                result, status = order_intake.decide_in_transaction(connection, body.review_id, data, actor=owner)
            except order_intake.OrderIntakeError as error:
                raise ChatError(error.code, str(error), error.status) from error
            task.update(status='COMPLETED' if result['applied'] else 'CANCELLED', issues=[])
            repo.save(connection, task)
            # Show blocked outcomes as recorded decisions, not a successful cancellation.
            message = f"Order decision: {body.action}. Reason: {body.reason}"
        else:
            try:
                extraction = offline_extract(message, session).model_dump()
            except (ValueError, ValidationError) as error:
                extraction = {'ambiguity': str(error) if not isinstance(error, ValidationError) else 'Please restate the order details using valid dates and quantities.'}
            prepare_in_transaction(connection, session, owner=owner, request_id=request_id,
                                   message=message, extraction=extraction)
        return _finish(connection, session, owner=owner, request_id=request_id, fingerprint=fingerprint,
                       action=action, message=message, payload={'message': message, 'order_decision': decision}, status=status)
