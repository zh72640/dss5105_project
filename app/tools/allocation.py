from .models import Workshop


def get_estimated_completion_time(
    workshop: Workshop,
    batch: dict,
    queues: dict
) -> float:
    """
    Calculate the estimated completion time for a given workshop and batch.

    Args:
        workshop (Workshop): The workshop to evaluate.
        batch (dict): The batch of orders.
        queues (dict): The current queues for each workshop.

    Returns:
        float: The estimated completion time (in number of days)
    """
    eta = batch["pieces"] / workshop.capacity + workshop.lead_days + queues[workshop.workshop_id]
    return eta


def get_lateness_score(
    workshop: Workshop,
    batch: dict,
    queues: dict
) -> float:
    """
    Calculate the lateness score for a given workshop and batch.

    Args:
        workshop (Workshop): The workshop to evaluate.
        batch (dict): The batch of orders.
        queues (dict): The current queues for each workshop.

    Returns:
        float: The lateness score.
    """
    eta = get_estimated_completion_time(workshop, batch, queues)
    allowed_days = (batch["due_date"] - batch["sent_date"]).days
    lateness_score = eta - allowed_days if workshop.status == "ACTIVE" else 10000
    return lateness_score


def get_defect_score(
    workshop: Workshop,
    batch: dict
) -> float:
    """
    Calculate the defect score for a given workshop and batch.

    Args:
        workshop (Workshop): The workshop to evaluate.
        batch (dict): The batch of orders.

    Returns:
        float: The defect score.
    """    
    return workshop.defect_rate if workshop.status == "ACTIVE" else 10000


def get_hybrid_score(
    workshop: Workshop,
    batch: dict,
    queues: dict
) -> float:
    """
    Calculate the hybrid score for a given workshop and batch.
    Objective is to choose the workshop that minimizes defects while meeting deadlines.

    Args:
        workshop (Workshop): The workshop to evaluate.
        batch (dict): The batch of orders.
        queues (dict): The current queues for each workshop.

    Returns:
        float: The hybrid score.
    """
    lateness_score = get_lateness_score(workshop, batch, queues)
    defect_score = get_defect_score(workshop, batch)

    hybrid_score = defect_score if lateness_score <= 0 else 10000
    return hybrid_score