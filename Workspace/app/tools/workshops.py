from .data import load_workshops
from .models import Workshop


def get_workshop(identifier: str) -> Workshop | None:
    key = identifier.casefold()
    return next((w for w in load_workshops().values()
                 if w.workshop_id.casefold() == key or w.name.casefold() == key), None)

