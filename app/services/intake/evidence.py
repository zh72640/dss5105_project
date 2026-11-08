"""Pure, bounded normalization and operation evidence shared by intake paths."""
import re
from datetime import date

from app.services.intake.normalization import PRODUCTS, WORKSHOPS, workshop_mentions

DATE_TOKEN = re.compile(
    r'\b(?:(?P<iso>\d{4}-\d{2}-\d{2})|'
    r'(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+'
    r'(?P<day>\d{1,2})(?:,?\s+(?P<year>\d{4}))?)\b', re.I)
MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']


def date_mentions(text, business_date):
    """Keep explicit years; yearless dates use the documented business year."""
    result = []
    for match in DATE_TOKEN.finditer(text):
        try:
            value = date.fromisoformat(match['iso']) if match['iso'] else date(
                int(match['year'] or date.fromisoformat(business_date).year),
                MONTHS.index(match['month'].lower()) + 1, int(match['day']))
        except ValueError:
            continue
        result.append((value.isoformat(), bool(match['iso'] or match['year'])))
    return result


def canonical_workshop(value, names=None):
    if not isinstance(value, str):
        return value
    table = WORKSHOPS if names is None else names
    matches = [wid for wid, name in table.items()
               if value.strip().casefold() in (wid.casefold(), name.casefold())]
    if len(matches) == 1:
        return matches[0]
    return value.strip().upper() if re.fullmatch(r'W\d+', value.strip(), re.I) else value


def canonical_product(value):
    if isinstance(value, str):
        for pattern, (name, _) in PRODUCTS.items():
            if re.fullmatch(pattern, value.strip(), re.I):
                return name
    return value


def product_evidence(value, quote):
    canonical = canonical_product(value)
    return literal_evidence(value, quote) or any(
        name == canonical and re.search(r'\b' + pattern + r'\b', quote, re.I)
        for pattern, (name, _) in PRODUCTS.items())


def category_evidence(value, quote):
    return value in ('TOPS', 'ACCESSORIES') and (literal_evidence(value, quote) or any(
        category == value and re.search(r'\b' + pattern + r'\b', quote, re.I)
        for pattern, (_, category) in PRODUCTS.items()))


def literal_evidence(value, quote):
    if not isinstance(value, str):
        return False
    phrase = r'\s+'.join(re.escape(word) for word in value.strip().split())
    return bool(phrase and re.search(r'(?<!\w)' + phrase + r'(?!\w)', quote, re.I))


def replaces_exclusions(text):
    return bool(re.search(r'\bonly\s+exclude\b|\breplace\b[^.!?;]*\bexclusions?\b|'
                          r'\bset\s+(?:the\s+)?exclusions?\s+(?:to|=)|仅排除|替换排除', text, re.I))


def clears_exclusions(text):
    if re.search(r"do not (?:clear|remove|drop)|don't (?:clear|remove|drop)|不要清除", text, re.I):
        return False
    return bool(re.search(r'\b(?:clear|remove|drop)\s+(?:all\s+|the\s+)?exclusions?\b|清除(?:全部)?排除', text, re.I))


def pending_due_date(text):
    """An explicitly pending replacement date cannot be satisfied by old DB facts."""
    return bool(re.search(r'(?:due date|deadline|ship date|交期|截止日期)', text, re.I) and
                re.search(r'will confirm|confirm[^.!?]*later|date[^.!?]*to follow|待确认|稍后确认', text, re.I))


def exclusion_operations(text, names=None):
    """Identify polarity at each mentioned workshop; ambiguous mentions stay unset."""
    result, last_end, previous = {}, 0, None
    for start, end, wid in workshop_mentions(text, names):
        prefix = text[last_end:start].lower()
        suffix = text[end:end + 45].lower()
        operation = None
        if re.search(r"do not exclude|don't exclude|not excluding|unexclude|restore|不排除|取消排除", prefix):
            operation = 'remove'
        elif re.search(r'\b(?:remove|drop)\s*$', prefix) and re.match(r'\s+from\s+(?:the\s+)?exclusions?', suffix):
            operation = 'remove'
        elif re.search(r"exclude|excluding|avoid|do not use|don't use|not to|not use|away from|nothing new to|排除|不用|不要", prefix):
            operation = 'add'
        elif re.match(r'\s+(?:must |should |is |be |remain |stay )*(?:not excluded|allowed again)', suffix):
            operation = 'remove'
        elif re.match(r'\s+(?:must |should |is |be |remain |stay )*(?:excluded|banned)', suffix):
            operation = 'add'
        elif previous and re.fullmatch(r'[\s,]*(?:and|or)?[\s,]*', prefix):
            operation = previous
        if operation:
            result.setdefault(wid, set()).add(operation)
        last_end, previous = end, operation
    return result


def normalize_patch(patch, message, context):
    """Canonicalize proven values, never manufacture facts or authorization."""
    if patch.quote not in message:
        return patch
    value, operation = patch.value, patch.op
    if patch.field in ('preferred_workshop', 'exclusion') and operation in ('set', 'add', 'remove'):
        names = context.get('workshop_names')
        if patch.field == 'exclusion':
            values = value if isinstance(value, list) else [value]
            value = [canonical_workshop(v, names) for v in values]
            # Ordinary exclusion instructions are additive, including legacy set output.
            if operation == 'set' and value and not replaces_exclusions(message):
                operation = 'add'
        else:
            value = canonical_workshop(value, names)
    elif patch.field == 'product' and operation == 'set':
        value = canonical_product(value)
    elif patch.field in ('due_date', 'order_date') and operation == 'set' and isinstance(value, str):
        # Correct only the inferred year, and only for matching month/day evidence.
        candidates = {v for v, explicit in date_mentions(patch.quote, context['business_date'])
                      if not explicit and v[5:] == value[5:]}
        if len(candidates) == 1:
            value = candidates.pop()
    return patch.model_copy(update={'value': value, 'op': operation})
