"""Fixed registration intake node: model extraction, deterministic preparation."""
import json
from pydantic import ValidationError

from app.db.database import Database
from app.db import agent_repository, chat_registration_repository
from app.agent.dynamic import record_model_start, record_model_response
from app.llm.errors import check_response, check_structured, text_content, translate_error
from app.llm.json_output import json_text
from app.prompts import get_registry
from app.schemas.order_registration import RegistrationExtraction
from app.services.chat import order_registration as registration
from app.services.chat.service import require_session


def run(state, runtime):
    context = runtime.context
    with Database(context.db_path) as db:
        session = require_session(db.connection, context.session_id, context.owner)
        saved = chat_registration_repository.step(db.connection, context.request_id)
        if saved:
            return _output(json.loads(saved['result_json']))
        cached = agent_repository.latest_extraction(db.connection, context.request_id, 'registration_extraction')
    prompt = get_registry().snapshot('order_registration.extract',
                                    version=cached.get('prompt_version') if cached else None)
    task = session.get('order_registration') or {}
    variables = {'context': {'draft': task.get('draft', {}), 'issues': task.get('issues', []),
                            'business_date': session['business_date']},
                 'output_schema': RegistrationExtraction.model_json_schema()}
    spec = context.registry.resolve('llm', context.model_key)
    model = context.registry.get_model('llm', context.model_key)
    feedback = None
    for attempt in range(cached['attempt'] if cached else 1, 3):
        if cached:
            candidate = cached['extracted']
            cached = None
        else:
            bundle = prompt.render(variables=variables, user_message=context.user_message)
            messages = bundle.as_messages()
            if feedback:
                messages.append({'role': 'user', 'content': 'Repair the extraction for the same message: ' + feedback})
            record_model_start(context, 'extract')
            try:
                if spec.output_method == 'prompt':
                    raw = model.invoke(messages)
                else:
                    structured = model.with_structured_output(RegistrationExtraction,
                        method=spec.output_method, include_raw=True).invoke(messages)
                    raw = structured.get('raw')
            except Exception as error:
                raise translate_error(error, spec.provider) from error
            record_model_response(context, 'extract', raw, bundle.metadata)
            check_response(raw, require_text=spec.output_method == 'prompt')
            try:
                candidate = json.loads(json_text(text_content(raw))) if spec.output_method == 'prompt' else check_structured(structured)[0]
                if hasattr(candidate, 'model_dump'):
                    candidate = candidate.model_dump()
                if getattr(raw, 'tool_calls', None) and spec.output_method == 'prompt':
                    candidate = None
            except (ValueError, TypeError):
                candidate = None
            with Database(context.db_path) as db, db.transaction() as connection:
                agent_repository.record_event(connection, session_id=context.session_id,
                    request_id=context.request_id, event_type='registration_extraction', detail={
                        'attempt': attempt, 'prompt_version': prompt.definition.version, 'extracted': candidate})
        try:
            extracted = registration.validate_extraction(candidate, context.user_message, session['business_date'], task.get('draft'))
            break
        except (ValueError, ValidationError) as error:
            feedback = str(error)[:1500]
    else:
        extracted = RegistrationExtraction(ambiguity='The order details could not be verified. Please restate them.')
    result = registration.prepare(context.session_id, owner=context.owner, request_id=context.request_id,
        message=context.user_message, expected_version=session['version'], db_path=context.db_path,
        extraction=extracted.model_dump())
    return _output(result)


def _output(result):
    return {'task_result': result, 'reply': result['result']['question'], 'source_node': 'order_registration',
            'pending_question': result['result']['question'] if result['status'] == 'waiting_user' else None,
            'response': None, 'tool_results': [], 'loaded_skills': {}}
