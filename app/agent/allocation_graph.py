"""Allocation-specific fixed preparation, Skill loading and guarded tool execution."""
import json
from typing import TypedDict

from langgraph.graph import START, END, StateGraph
from langgraph.runtime import Runtime

from app.agent import skills
from app.services.chat.context import build_context
from app.services.chat import extraction
from app.agent.dynamic import AgentContext, record_model_response, record_model_start
from app.llm.errors import check_response, check_structured, text_content, translate_error
from app.llm.json_output import json_text
from app.agent.executor import run as run_executor, waiting_skill_snapshots
from app.db.database import Database
from app.db.chat_repository import snapshot
from app.db import agent_repository
from app.prompts import get_registry
from app.schemas.chat import TurnInterpretation, AllocationExtraction
from app.services.allocation.contracts import inspect_input, single_workshop_issues
from app.services.chat.completion import BASIC_ALLOCATION_POLICY
from app.services.chat import allocation_preparation
from app.tools.registry import TOOLS, allowed_for_task


MAX_EXTRACTION_ATTEMPTS = 2


class AllocationState(TypedDict, total=False):
    messages: list
    interpretation: dict
    sequence: int
    preparation: dict
    loaded_skills: dict
    task_result: dict
    tool_results: list
    pending_question: str | None
    skill_input: dict


def _failed(code, message, task_id=""):
    return {"task_id": task_id, "task_type": "allocation", "status": "failed",
            "result": None, "issues": [{"code": code, "field": "workflow",
                                         "severity": "blocking", "question": message}]}


def extract_fields(state: AllocationState, runtime: Runtime[AgentContext]):
    context = runtime.context
    with Database(context.db_path) as db:
        session = snapshot(db.connection, context.session_id, context.owner)
        if session is None:
            return {"task_result": _failed("SESSION_NOT_FOUND", "The session is unavailable.")}
        conversation = build_context(db.connection, session)
        saved = agent_repository.latest_extraction(db.connection, context.request_id)
    prompt = get_registry().snapshot("allocation.extract",
        version=saved.get('prompt_version') if saved else None)
    variables = {"context": {"business_date": conversation['business_date']},
                 "output_schema": AllocationExtraction.model_json_schema()}
    spec = context.registry.resolve("llm", context.model_key)
    model = context.registry.get_model("llm", context.model_key)
    attempt = saved['attempt'] if saved else 1
    feedback = None
    while attempt <= MAX_EXTRACTION_ATTEMPTS:
        cached = saved is not None
        result = saved or _extract_once(context, model, spec, prompt, variables, attempt,
                                        feedback, conversation['current_sequence'])
        saved = None
        try:
            if result.get('parsing_error'):
                raise extraction.ExtractionValidationError('format', {
                    **extraction.format_details(ValueError('INVALID_EXTRACTION_FORMAT'),
                        result.get('extracted'), context.user_message, conversation['current_sequence']),
                    **result['parsing_error']})
            interpretation = extraction.validate_candidate(result.get('extracted'),
                message=context.user_message, conversation=conversation)
        except extraction.ExtractionValidationError as error:
            detail = {'attempt': attempt, 'stage': error.stage, **error.detail}
            if not cached or not result.get('validation_recorded'):
                _record_extraction_event(context, 'extraction_validation_failed', detail)
            if attempt == MAX_EXTRACTION_ATTEMPTS:
                failure = _failed('EXTRACTION_FORMAT_INVALID' if error.stage == 'format' else
                    'EXTRACTION_EVIDENCE_INVALID', extraction.failure_message(error.stage, detail),
                    session['task']['task_id'])
                failure['issues'][0].update(field=detail.get('field') or 'workflow',
                                           reason=detail['reason'], attempts=attempt)
                return {'task_result': failure}
            feedback = {'validation': detail, 'previous_output': result.get('raw_text'),
                        'previous_extraction': result.get('extracted')}
            attempt += 1
            continue
        return {"interpretation": interpretation.model_dump(),
                "sequence": conversation["current_sequence"]}


def _extract_once(context, model, spec, prompt, variables, attempt, feedback, sequence):
    bundle = prompt.render(variables=variables, user_message=context.user_message,
                           retry_feedback=json.dumps(feedback, ensure_ascii=False) if feedback else None)
    record_model_start(context, "extract")
    try:
        if spec.output_method == "prompt":
            raw = model.invoke(bundle.as_messages())
            response = None
        else:
            response = model.with_structured_output(AllocationExtraction, method=spec.output_method,
                include_raw=True).invoke(bundle.as_messages())
            raw = response.get("raw") if isinstance(response, dict) else None
    except Exception as error:
        raise translate_error(error, spec.provider) from error
    if raw is None:
        # Missing transport envelopes remain model errors, not extraction repairs.
        check_structured(response)
    record_model_response(context, "extract", raw, bundle.metadata)
    check_response(raw, require_text=spec.output_method == 'prompt')
    text = text_content(raw)
    raw_calls = getattr(raw, 'tool_calls', []) or []
    invalid_calls = getattr(raw, 'invalid_tool_calls', []) or []
    parsing_error = None
    if spec.output_method == 'prompt':
        try:
            candidate = json.loads(json_text(text))
        except (ValueError, TypeError):
            candidate = None
            parsing_error = {'reason': 'INVALID_JSON',
                             'errors': [{'location': [], 'type': 'json_invalid'}]}
    else:
        candidate = response.get('parsed')
        structured_error = response.get('parsing_error')
        if hasattr(candidate, 'model_dump'):
            candidate = candidate.model_dump(mode='json')
        missing_parsed = candidate is None
        if candidate is None and text:
            # Recover output for diagnostics only; an SDK parse failure remains a failure.
            try:
                candidate = json.loads(json_text(text))
            except (ValueError, TypeError):
                pass
        if candidate is None and len(raw_calls) == 1:
            candidate = raw_calls[0].get('args')
        if candidate is None and len(invalid_calls) == 1:
            try:
                candidate = json.loads(invalid_calls[0].get('args', ''))
            except (ValueError, TypeError):
                pass
        if structured_error or missing_parsed:
            error = structured_error or ValueError('INVALID_EXTRACTION_FORMAT')
            parsing_error = extraction.format_details(error, candidate, context.user_message, sequence)
    result = {'contract': 'allocation_extraction_v1', 'attempt': attempt,
              'runtime_message_sequence': sequence, 'raw_tool_calls': raw_calls,
              'invalid_tool_calls': invalid_calls,
              'prompt_version': prompt.definition.version, 'raw_text': text,
              'extracted': candidate, 'parsing_error': parsing_error}
    _record_extraction_event(context, 'allocation_extraction', result)
    return result


def _record_extraction_event(context, kind, detail):
    """Persist extraction attempts and diagnostics in the existing owner-scoped trace."""
    with Database(context.db_path) as db, db.transaction() as connection:
        agent_repository.record_event(connection, session_id=context.session_id,
            request_id=context.request_id, event_type=kind, detail=detail)


def prepare(state: AllocationState, runtime: Runtime[AgentContext]):
    context = runtime.context
    interpretation = TurnInterpretation.model_validate(state["interpretation"])
    prepared = allocation_preparation.prepare(
        db_path=context.db_path, session_id=context.session_id, owner=context.owner,
        request_id=context.request_id, interpretation=interpretation, as_of=context.as_of,
        sequence=state["sequence"])
    skill_input, issues = inspect_input(prepared.get("skill_input") or prepared["task"]["draft"])
    issues += single_workshop_issues(prepared["task"]["draft"])
    if issues and prepared["ready"]:
        prepared = {**prepared, "ready": False, "issues": issues}
    if not prepared["ready"]:
        return {"preparation": prepared, "task_result": {
            "task_id": prepared["task"]["task_id"], "task_type": "allocation",
            "status": "blocked", "result": None, "issues": prepared["issues"]}}
    return {"preparation": prepared, "skill_input": skill_input}


def load_allocation_skill(state: AllocationState, runtime: Runtime[AgentContext]):
    pinned = waiting_skill_snapshots(runtime.context, "allocation")
    item = pinned.get("allocation-recommendation") or skills.load(
        "allocation-recommendation", runtime.context.skill_root)
    if any(name not in TOOLS or not allowed_for_task(name, "allocation") for name in item["tools"]):
        return {"task_result": _failed("SKILL_TOOL_UNAVAILABLE",
            "The allocation instructions require an unavailable tool.",
            state["preparation"]["task"]["task_id"])}
    return {"loaded_skills": {item["name"]: item}}


def execute_allocation(state: AllocationState, runtime: Runtime[AgentContext]):
    history = state.get("messages", [])
    result = run_executor(runtime.context, task_type="allocation",
                          loaded_skills=state["loaded_skills"],
                          seed_history=history[:-1] if history else (),
                          execution_policy=BASIC_ALLOCATION_POLICY, skill_input=state["skill_input"])
    task_result = result.get("task_result") or _failed("INCOMPLETE_RECOMMENDATION",
        "No verified recommendation was saved.", state["preparation"]["task"]["task_id"])
    return {"task_result": task_result,
            "tool_results": result.get("tool_results", []),
            "pending_question": result.get("pending_question"),
            "loaded_skills": result.get("loaded_skills", state["loaded_skills"])}


def route_after_extract(state):
    return END if state.get("task_result") else "prepare"


def route_after_prepare(state):
    return END if state.get("task_result") else "load_skill"


def route_after_skill(state):
    return END if state.get("task_result") else "executor"


def build_graph():
    graph = StateGraph(AllocationState, context_schema=AgentContext)
    graph.add_node("extract", extract_fields)
    graph.add_node("prepare", prepare)
    graph.add_node("load_skill", load_allocation_skill)
    graph.add_node("executor", execute_allocation)
    graph.add_edge(START, "extract")
    graph.add_conditional_edges("extract", route_after_extract, {"prepare": "prepare", END: END})
    graph.add_conditional_edges("prepare", route_after_prepare, {"load_skill": "load_skill", END: END})
    graph.add_conditional_edges("load_skill", route_after_skill, {"executor": "executor", END: END})
    graph.add_edge("executor", END)
    return graph.compile()
