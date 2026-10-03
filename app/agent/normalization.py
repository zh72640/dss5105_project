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
           "six": 6, "seven": 7, "eight": 8, "一": 1, "两": 2, "二": 2, "三": 3}
NUMBER = r"(?:-?\d+(?:\.\d+)?|zero|one|two|three|four|five|six|seven|eight|一|两|二|三)"


def number(value):
    return NUMBERS[value.lower()] if value.lower() in NUMBERS else float(value) if "." in value else int(value)


def workshop_mentions(text):
    found = [(m.start(), m.end(), f"W{int(m.group(1))}") for m in re.finditer(r"\bW0*(\d+)\b", text, re.I)]
    for wid, name in WORKSHOPS.items():
        found.extend((m.start(), m.end(), wid) for m in re.finditer(r"\b" + re.escape(name) + r"\b", text, re.I))
    return sorted(found)


def order_ids(text):
    return list(dict.fromkeys(m.group().upper() for m in re.finditer(r"\b(?:ORD-\d{3}|O\d+)\b", text, re.I)))
