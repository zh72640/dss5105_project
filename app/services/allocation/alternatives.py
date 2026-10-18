"""Read-only, explicitly conditional alternatives for an infeasible request."""
from copy import deepcopy

from app.allocator import AllocationRequest, allocate


def suggest(order, workshops, constraints, as_of, *, max_workshops=1):
    """Find a bounded set of options; never mutate or authorize requirements.

    Capability, status and exclusions are never relaxed. Each option states every
    requested change, including a new objective when comparing earliest delivery.
    The caller must run a new recommendation after the user authorizes a change.
    """
    remaining = {**order, "pieces": order["pieces"] - order.get("completed_pieces", 0)}
    preferred = constraints.get("preferred_workshop")
    hard = bool(constraints.get("deadline_required"))
    objective = constraints.get("objective") or "min_delay"
    proposals, seen = [], set()
    for clear_required in ((False, True) if preferred else (False,)):
        for allow_late in ((False, True) if hard else (False,)):
            objectives = (objective, "min_delay") if allow_late and objective != "min_delay" else (objective,)
            for analysis_objective in objectives:
                for limit in range(max_workshops, min(8, len(workshops)) + 1):
                    if preferred and not clear_required and limit > max_workshops:
                        break
                    changes = {}
                    if clear_required:
                        changes["preferred_workshop"] = None
                    if allow_late:
                        changes["deadline_required"] = False
                    if limit != max_workshops:
                        changes["num_workshop_allowed"] = limit
                    if analysis_objective != objective:
                        changes["objective"] = analysis_objective
                    if not changes:
                        continue
                    effective = {**deepcopy(constraints), "num_workshop_allowed": limit, **changes}
                    result = allocate(AllocationRequest(
                        order=remaining, workshops=workshops, as_of=as_of,
                        objective=analysis_objective, max_workshops=limit,
                        exclusion=list(constraints.get("exclusion") or []),
                        preferred_workshop=effective.get("preferred_workshop"),
                        deadline_required=bool(effective.get("deadline_required"))))
                    if not result["success"]:
                        continue
                    plan = result["candidate_plans"][0]
                    identity = (tuple(sorted(changes.items())),
                                tuple(sorted((p["workshop_id"], p["pieces"]) for p in plan["allocation"])))
                    if identity not in seen:
                        seen.add(identity)
                        proposals.append({"required_changes": changes, "plan": plan,
                                          "effective_constraints": effective,
                                          "requires_authorization": True, "committed": False,
                                          "supported_mode": "offline" if len(plan["allocation"]) > 1 else "any"})
                    # The smallest successful workshop limit is sufficient for this branch.
                    break
    proposals.sort(key=lambda item: (len(item["required_changes"]),
                                     item["plan"]["estimated_days"], item["plan"]["estimated_cost"]))
    return proposals[:5]


def describe(option):
    """English explanation shared by offline feedback and blocked Agent results."""
    labels = {
        "preferred_workshop": lambda value: "remove the required sole workshop",
        "deadline_required": lambda value: "allow delivery after the registered due date",
        "num_workshop_allowed": lambda value: f"allow up to {value} workshops",
        "objective": lambda value: "use earliest completion as the objective",
    }
    required = "; ".join(labels[field](value) for field, value in option["required_changes"].items())
    plan = option["plan"]
    parts = ", ".join(f"{part['workshop_id']} ({part['pieces']} pieces)" for part in plan["allocation"])
    suffix = " Split planning is currently available in Offline mode only." if option["supported_mode"] == "offline" else ""
    return (f"If you explicitly authorize: {required}. A feasible option is {parts}, "
            f"estimated {plan['estimated_delivery_date']}, cost {plan['estimated_cost']:.2f}, "
            f"weighted defect rate {plan['expected_defect_rate']:.2%}. "
            "This is a suggestion only; request a new recommendation before confirming." + suffix)


def attach(report, order, workshops, as_of, *, max_workshops=1):
    """Attach only after validated business constraints cause a known infeasibility."""
    allowed = {"PREFERRED_INELIGIBLE", "DEADLINE_INFEASIBLE", "CAPACITY_INFEASIBLE", "NO_ELIGIBLE_WORKSHOP"}
    problems = report["blocking_issues"]
    if not order or not problems or any(item["code"] not in allowed for item in problems):
        return
    options = suggest(order, workshops, report["effective_constraints"], as_of, max_workshops=max_workshops)
    report["alternatives"] = options
    report["alternatives_status"] = "authorization_required" if options else "no_known_feasible_alternative"
    problems[0]["alternatives"] = options
    problems[0]["alternatives_status"] = report["alternatives_status"]


def issue_messages(issues):
    """Ground refusal prose in the same conditional options used by the UI."""
    messages = []
    for item in issues:
        if item.get("question"):
            messages.append(item["question"])
        messages.extend(describe(option) for option in item.get("alternatives", [])[:2])
        if item.get("alternatives_status") == "no_known_feasible_alternative":
            messages.append("No known feasible alternative preserves workshop capability, status and your exclusions.")
    return list(dict.fromkeys(messages))
