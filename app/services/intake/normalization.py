"""Vocabulary only: no order records, queues, costs or business selection."""
import re

WORKSHOPS = {"W1": "QuickStitch", "W2": "SteadyHands", "W3": "BudgetWorks",
             "W4": "Little Loom", "W5": "GiantWeave", "W6": "Nimble Needle",
             "W7": "OldMill", "W8": "FreshStart"}
PRODUCTS = {"crewneck sweaters?": ("Crewneck sweater", "TOPS"),
            "polo shirts?": ("Polo shirt", "TOPS"), "cardigans?": ("Cardigan", "TOPS"),
            "hoodies?": ("Hoodie", "TOPS"), "vests?": ("Vest", "TOPS"),
            "scar(?:f|ves)": ("Scarf", "ACCESSORIES"), "beanies?": ("Beanie", "ACCESSORIES")}
NUMBERS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
           "six": 6, "seven": 7, "eight": 8, "\u4e00": 1, "\u4e24": 2, "\u4e8c": 2, "\u4e09": 3}
NUMBER = r"(?:-?\d+(?:\.\d+)?|zero|one|two|three|four|five|six|seven|eight|\u4e00|\u4e24|\u4e8c|\u4e09)"


def number(value):
    return NUMBERS[value.lower()] if value.lower() in NUMBERS else float(value) if "." in value else int(value)


def workshop_mentions(text, names=None):
    found = [(m.start(), m.end(), f"W{int(m.group(1))}") for m in re.finditer(r"\bW0*(\d+)\b", text, re.I)]
    for wid, name in (WORKSHOPS if names is None else names).items():
        found.extend((m.start(), m.end(), wid) for m in re.finditer(r"\b" + re.escape(name) + r"\b", text, re.I))
    return sorted(found)


def order_ids(text, *, allow_short=False):
    """Return distinct references in text order, optionally expanding labeled lists.

    Short numbers require an order label or a list anchored by an explicit ID.
    List separators never extend across prose; quantities, dates and ranges are
    not order references. This recognizes vocabulary only, without selecting an
    order or looking up registered facts.
    """
    canonical = r"(?:ORD(?:-\s*|\s+)\d{1,3}(?!\w|[./-]\d)|O\d+\b)"

    def normalized(value):
        # ORD spacing and zero padding describe the same registered reference.
        if value.upper().startswith('ORD'):
            return f"ORD-{int(re.search(r'\d+', value).group()):03d}"
        return f"ORD-{int(value):03d}" if value.isdigit() else value.upper()

    identifiers = [(m.start(), normalized(m.group())) for m in re.finditer(r"\b" + canonical, text, re.I)]
    if allow_short:
        # Test the whole numeric phrase before consuming a list member. Reuse
        # product vocabulary so quantities like "300 vests" and "1,200 scarves"
        # cannot become order IDs, including the first group of a comma quantity.
        units = rf"(?:pieces?|units?|workshops?|shops?|days?|percent|{'|'.join(PRODUCTS)})\b|%"
        quantity = rf"\d+(?:,\d{{3}})*(?:\.\d+)?\s*(?:{units})"
        short = rf"(?!{quantity})\d{{1,3}}(?!\w|[./-]\d)"
        token = rf"(?:{canonical}|{short})"
        label = r"\borders?(?:\s+(?:ids?|numbers?|nos?\.?))?\s*[:#]?\s*"
        separator = r"(?:\s*,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+)"
        references = re.finditer(rf"(?:{label}{token}|\b{canonical})(?:{separator}{token})*", text, re.I)
        for match in references:
            for item in re.finditer(rf"\b{token}", match.group(), re.I):
                value = normalized(item.group())
                identifiers.append((match.start() + item.start(), value))
    return list(dict.fromkeys(value for _, value in sorted(identifiers)))
