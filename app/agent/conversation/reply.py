"""Format business feedback from verified results and saved facts."""
from app.prompts import get_registry

OBJECTIVES = {"min_delay": "earliest completion", "min_cost": "lowest cost",
              "min_defects": "lowest defect rate", "hybrid": "weighted time and quality"}


def solution_reply(result, order_id, committed=False):
    parts = "; ".join(f"workshop {p['workshop_id']} ({p['workshop_name']}): {p['pieces']} pieces"
                      for p in result["allocation"])
    total = sum(p["pieces"] for p in result["allocation"])
    tail = ("The allocation has been committed." if committed else
            "Confirm this recommendation to commit it. The order and queues have not changed.")
    return (f"{'Committed' if committed else 'Recommend'} {total} pieces of {order_id} to {parts}. "
            f"Estimated completion: {result['estimated_delivery_date']}; estimated cost: "
            f"{result['estimated_cost']:.2f}. {tail}")


def clarification_reply(report):
    questions = list(dict.fromkeys(p["question"] for p in report["blocking_issues"]))
    return "Please resolve the following:\n" + "\n".join(questions)


def explain(session, message):
    rec = session["recommendation"]
    if not rec:
        return "There is no checked recommendation yet. Provide an order and requirements first."
    result = rec["committed_result"] or rec["result"]
    status = {"confirmed": "Committed result", "valid": "Current recommendation",
              "superseded": "Superseded recommendation"}[rec["status"]]
    reasons = {"excluded_by_user": "excluded by your requirement", "cannot_make_tops": "cannot make tops",
               "cannot_make_accessories": "cannot make accessories", "status_suspended": "suspended",
               "status_closed": "closed", "invalid_capacity_or_queue": "invalid capacity or queue"}
    rejected = "; ".join(f"{wid}: {reasons.get(reason, 'ineligible for this batch')}"
                         for wid, reason in result.get("rejected", {}).items())
    deadline = "meets" if result.get("deadline_met") else "misses"
    summary = solution_reply(result, session["task"]["draft"]["order_id"], rec["status"] == "confirmed")
    if rec["status"] == "superseded":
        summary += " This historical recommendation cannot be confirmed."
    return (summary + "\n" + f"{status} uses the {OBJECTIVES.get(result['objective'], result['objective'])} objective. "
            f"The estimated date {deadline} the registered due date. Estimated completion: "
            f"{result['estimated_delivery_date']}; estimated cost: {result['estimated_cost']:.2f}."
            + (f" Other workshop rejections: {rejected}." if rejected else ""))


def conversational_reply(message, context, registry, mode, model_key):
    if mode == "llm":
        bundle = get_registry().render("conversation.reply", variables={"context": context}, user_message=message)
        result, execution = registry.invoke_task(mode, model_key, bundle)
        content = result["text"]
        if any(word in content.lower() for word in ("allocation committed", "successfully allocated")):
            content = "Check the saved commitment result for allocation status. This reply did not commit an allocation."
        return content, execution
    return ("I can query orders and workshops, check allocation requirements, explain recommendations, "
            "and revise constraints. Provide an order ID and your requirements. Offline mode is a rules demo; "
            "choose a configured model for the dynamic Agent."), None
