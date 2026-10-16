"""Shared deterministic allocation decisions and transactional business writes."""
from app.allocator import AllocationRequest, allocate
from app.db import allocation_repository as repo
from app.db.order_repository import retrieve
from app.db.workshop_repository import get_all
from app.services.queue import advance


def terminal(status, code, message):
    return {"success": False, "decision_status": status, "allocation": [], "reason_codes": [code],
            "warnings": [], "message": message, "candidate_ranking": []}


def _planning_max_workshops(limit, sources=None):
    """Chat/Agent: only provenanced limits >=2 enable multi-workshop planning."""
    authorized = sources is not None and "num_workshop_allowed" in sources
    return limit if (authorized and type(limit) is int and limit >= 2) else 1


def recommend(connection, draft, as_of, pending=(), sources=None):
    from app.services.allocation_preflight import preflight, check_solution, digest
    report, order, workshops, facts_hash = preflight(connection, draft, as_of, pending, sources)
    trace = {'db_changes': [], 'order': order}
    if not report['ready_for_planning']:
        return report, None, trace, None, None
    constraints = report['effective_constraints']
    max_workshops = _planning_max_workshops(constraints['num_workshop_allowed'], sources)
    report['planning_max_workshops'] = max_workshops
    remaining = {**order, 'pieces': order['pieces'] - order['completed_pieces']}
    result = allocate(AllocationRequest(
        order=remaining, workshops=workshops, as_of=as_of,
        objective=constraints['objective'], exclusion=list(constraints['exclusion']),
        preferred_workshop=constraints['preferred_workshop'],
        deadline_required=constraints['deadline_required'], max_workshops=max_workshops))
    check_solution(result, order, workshops, draft, report, as_of)
    trace.update(queue={w.workshop_id: w.queue_days for w in workshops},
        eligible_workshops=result.get('eligible_workshops', []), rejected_workshops=result.get('rejected', {}))
    plan_hash = digest({k: result.get(k) for k in ('allocation', 'objective', 'estimated_delivery_date', 'estimated_cost', 'warnings')})
    return report, result, trace, facts_hash, plan_hash


def decide(connection, parsed, objective, as_of, trace, *, max_workshops=1):
    """Decide an allocation. Default max_workshops=1 (seed / single-workshop product rule)."""
    if parsed.parse_status != "ok":
        if parsed.parse_status == "invalid":
            return terminal("DECLINE", "INVALID_REQUEST", "Unsupported or invalid request: " + ", ".join(parsed.ambiguities))
        return terminal("CLARIFY", "PARSER_NEEDS_CLARIFICATION", "Please provide a complete new message: " +
                        ", ".join(parsed.missing_fields + parsed.ambiguities))
    order, issue = retrieve(connection, parsed)
    if order:
        trace["order"] = order
    if issue:
        status = "DECLINE" if issue == "ORDER_NOT_FOUND" else "CLARIFY"
        return terminal(status, issue, "Order lookup could not establish a matching record; no allocation was attempted.")
    if order["state"] in ("WORKING", "COMPLETED", "LAPSED"):
        return terminal("REFUSE", "ORDER_ALREADY_" + order["state"], "Order state prevents another allocation.")
    workshops = get_all(connection, as_of)
    trace["workshop_count"] = len(workshops)
    trace["queue"] = {w.workshop_id: w.queue_days for w in workshops}
    unknown = set(parsed.exclusion) - {w.workshop_id for w in workshops}
    if unknown:
        return terminal("CLARIFY", "UNKNOWN_EXCLUDED_WORKSHOP", "Unknown workshop ID(s): " + ", ".join(sorted(unknown)))
    if type(max_workshops) is not int or not 1 <= max_workshops <= 8:
        return terminal("ERROR", "INVALID_ARGUMENT", "max_workshops must be an integer from 1 to 8.")
    remaining_order = {**order, "pieces": order["pieces"] - order["completed_pieces"]}
    result = allocate(AllocationRequest(
        order=remaining_order, workshops=workshops, as_of=as_of,
        objective=parsed.objective or objective, exclusion=list(parsed.exclusion or []),
        preferred_workshop=parsed.preferred_workshop,
        deadline_required=bool(parsed.deadline_required), max_workshops=max_workshops))
    trace["eligible_workshops"] = result["eligible_workshops"]
    trace["rejected_workshops"] = result["rejected"]
    return result


def apply(connection, request_id, result, trace, as_of):
    changes = trace["db_changes"]
    order = trace.get("order")
    if not order or order["state"] not in ("READY", "UNASSIGNED"):
        return
    if result["success"]:
        if sum(p["pieces"] for p in result["allocation"]) != order["pieces"] - order["completed_pieces"]:
            raise ValueError("PIECES_CONSERVATION_FAILED")
        for part in result["allocation"]:
            advance(connection, part["workshop_id"], as_of)
            capacity = repo.capacity(connection, part["workshop_id"])
            repo.insert_working_order(connection, order["order_id"], part, request_id,
                                      result["objective"], capacity)
            # Processing consumes queue; transport is not workshop production capacity.
            after = part["queue_days"] + part["processing_days"]
            repo.set_queue(connection, part["workshop_id"], after, as_of)
            changes.append({"table": "workshop_queue", "workshop_id": part["workshop_id"],
                            "before": part["queue_days"], "after": after})
        repo.mark_working(connection, order["order_id"])
        changes.append({"table": "working_order", "inserted_rows": len(result["allocation"]), "order_id": order["order_id"]})
    elif result["decision_status"] == "ESCALATE" or (result["decision_status"] == "REFUSE" and "rejected" in result):
        repo.mark_unassigned(connection, order["order_id"], request_id, result["reason_codes"][0])
        changes.append({"table": "unassigned_order", "order_id": order["order_id"], "reason": result["reason_codes"][0]})


def record(connection, request_id, fingerprint, message, outcome, response):
    repo.record_decision(connection, request_id, fingerprint, message, outcome, response)
