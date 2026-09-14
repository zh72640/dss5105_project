from .models import Workshop


def exclusion_reason(workshop: Workshop, category: str, pieces: int, excluded: list[str]) -> str | None:
    excluded_keys = {x.casefold() for x in excluded}
    if workshop.name.casefold() in excluded_keys or workshop.workshop_id.casefold() in excluded_keys:
        return "excluded_by_user"
    if workshop.status != "ACTIVE":
        return f"status_{workshop.status.lower()}"
    if category not in workshop.makes:
        return f"cannot_make_{category.lower()}"
    if workshop.max_batch is not None and pieces > workshop.max_batch:
        return f"exceeds_{workshop.max_batch}_piece_limit"
    return None

