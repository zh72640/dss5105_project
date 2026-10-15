"""Model-backed interpretation over shared deterministic evidence policy."""
import json
import re
from app.schemas.chat import TurnInterpretation
from app.prompts import get_registry
from app.services.interpretation import rule_interpret, validate_interpretation, FIELDS

def interpret(message, context, registry=None, mode='offline', model_key=None):
    baseline=rule_interpret(message,context)
    telemetry={'backend':mode,'workflow':'chat_graph_v2','context_sequences':[m['sequence'] for m in context['history']]}
    if mode=='llm' and baseline.intent not in ('confirm_allocation','new_request','cancel_task','reject_recommendation'):
        bundle=get_registry().render('conversation.interpret',variables={'context':context,'output_schema':TurnInterpretation.model_json_schema()},user_message=message)
        result, execution=registry.invoke_task(mode,model_key,bundle)
        value=TurnInterpretation.model_validate_json(result['text'])
        validate_interpretation(value,message,context)
        # All recognized sub-constraints must survive model interpretation.
        represented={(p.field,p.op,json.dumps(p.value,sort_keys=True)) for p in value.patch_operations}
        for p in baseline.patch_operations:
            if (p.field,p.op,json.dumps(p.value,sort_keys=True)) not in represented:
                value.patch_operations.append(p)
        value.unsupported_constraints=list(set(value.unsupported_constraints+baseline.unsupported_constraints))
        if baseline.ambiguity_reason and (baseline.patch_operations or any(code in baseline.ambiguity_reason for code in ('conflicting_', 'multiple_', 'invalid_', 'relative_', 'negated_'))):
            value.ambiguity_reason=baseline.ambiguity_reason
        telemetry.update(execution=execution,usage=result.get('usage'))
        if value.intent=='confirm_allocation' and baseline.intent!='confirm_allocation':
            value.intent='modify_constraints' if value.patch_operations else 'unsupported_or_ambiguous'
            if not value.patch_operations:
                value.ambiguity_reason='Confirm the current recommendation explicitly; a question or ambiguous wording cannot commit it.'
        if (value.patch_operations or value.unsupported_constraints) and value.intent in ('query_order','query_workshop','explain_recommendation','help_or_chat'):
            value.intent='modify_constraints'
        if re.search(r'如果|假如|\bif\b|what if',message,re.I):
            value.intent='explain_recommendation'
            value.patch_operations=[]
            value.unsupported_constraints=[]
    else:
        value=baseline
    validate_interpretation(value,message,context)
    return value,telemetry
