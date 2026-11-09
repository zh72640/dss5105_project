"""Prepare inspectable alternatives without changing allocation requirements or production."""
from copy import deepcopy

from app.allocator import allocate
from app.db.database import Database
from app.db import chat_repository, preparation_repository
from app.services.allocation.service import prepare_recommendation
from app.services.allocation.contracts import add_order_snapshot, single_workshop_issues
from app.services.allocation.preflight import issue
from app.services.chat.alternative_acceptance import track_report


def prepare(*, db_path, session_id, owner, request_id, as_of):
    """Persist up to five exact-workshop preview offers with fresh planner dates.

    The sole-workshop constraint is relaxed on a copy for comparison. Exclusions,
    hard deadlines, facts and unresolved requirements remain enforced. A candidate
    is authorization data, never a saved confirmable recommendation or allocation.
    Results are request-cached for checkpoint recovery; selection runs fresh checks.
    """
    with Database(db_path) as db, db.transaction() as connection:
        session = chat_repository.snapshot(connection, session_id, owner)
        if session is None or session['status'] != 'OPEN':
            raise ValueError('SESSION_NOT_FOUND')
        cached = preparation_repository.existing(connection, request_id, 'alternatives_prepared')
        if cached is not None:
            if cached['task_id'] != session['task']['task_id']:
                raise ValueError('IDEMPOTENCY_CONFLICT')
            return cached
        task = deepcopy(session['task'])
        if task['state'] in ('CONFIRMED', 'CANCELLED'):
            return _result(task, [], [issue('TASK_CLOSED', 'task', 'Create a new request for another allocation.')])
        draft = deepcopy(task['draft'])
        draft['preferred_workshop'] = None
        pending = list(task['issues']) + single_workshop_issues(draft)
        prepared = prepare_recommendation(connection, draft, as_of, pending, task['sources'])
        order = prepared['order']
        proposals = []
        if prepared['request'] is not None:
            computed = allocate(prepared['request'])
            # These are the same ranked plans and rounded dates used for saved recommendations.
            proposals = [{'plan': plan, 'required_changes': {}}
                         for plan in computed.get('candidate_plans', [])]
        else:
            # Known infeasibility may offer explicitly labelled deadline/objective changes.
            proposals = prepared['report'].get('alternatives', [])
        current = session.get('recommendation')
        current_ids = {p['workshop_id'] for p in current['result']['allocation']} if (
            current and current['status'] == 'valid') else set()
        options = []
        for proposal in proposals:
            plan = proposal['plan']
            if len(plan['allocation']) != 1:
                continue
            wid = plan['allocation'][0]['workshop_id']
            if wid == task['draft'].get('preferred_workshop') or wid in current_ids:
                continue
            changes = {**proposal['required_changes'], 'preferred_workshop': wid}
            snapshot = add_order_snapshot(order, {**plan, 'success': True})
            options.append({'offer_type': 'workshop_candidate', 'plan': snapshot,
                'required_changes': changes, 'requires_authorization': True,
                'committed': False, 'supported_mode': 'any'})
        options = options[:5]
        if options:
            updated = {**task['report'], 'alternatives': options,
                       'alternatives_status': 'authorization_required'}
            task['report'] = track_report(task, updated, task['report'])
            options = task['report']['pending_alternatives']
            chat_repository.save_task(connection, task)
            result = _result(task, options, [])
        else:
            problems = prepared['report']['blocking_issues'] or [issue('NO_OTHER_OPTIONS', 'constraints',
                'No additional single-workshop option satisfies the current requirements. State which requirement you want to revise.')]
            task['report'].update(alternatives=[], pending_alternatives=[],
                                  alternatives_status='no_known_feasible_alternative')
            chat_repository.save_task(connection, task)
            result = _result(task, [], problems)
        preparation_repository.record(connection, session_id, request_id, result, 'alternatives_prepared')
        return result


def _result(task, options, issues):
    """Return the standard business result; presentation owns its visible table."""
    text = ('Other workshop options for ' + str(task['draft'].get('order_id')) +
            '. These are comparison previews. Your requirements have not changed. '
            'Choose a workshop or option to generate a fresh recommendation before confirming.')
    if options and options[0]['plan'].get('due_date') is None:
        text += ' No confirmed due date is available; lateness cannot be assessed.'
    return {'task_id': task['task_id'], 'task_type': 'allocation',
            'status': 'waiting_user' if options else 'blocked',
            'result': {'question': text, 'alternatives': options} if options else None,
            'issues': issues}
