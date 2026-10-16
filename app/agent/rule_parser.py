"""Explicitly offline baseline. Rules match language, never fixture request IDs."""
import re
from datetime import date
from app.schemas.parser_schema import ParseResult
from .normalization import PRODUCTS, NUMBER, number, order_ids, workshop_mentions


def extract(message: str, reference_date: date) -> dict:
    text = message.replace("’", "'").replace("—", " ")
    low = text.lower()
    out = ParseResult().to_dict()
    ambiguities = out["ambiguities"]
    ids = order_ids(text)
    if len(ids) == 1:
        out["order_id"] = ids[0]
    elif len(ids) > 1:
        ambiguities.append("multiple_order_ids")
    products = [(m, name, category) for pattern, (name, category) in PRODUCTS.items()
                for m in re.finditer(r"\b" + pattern + r"\b", text, re.I)]
    if len({p[1] for p in products}) == 1:
        out["product"], out["category"] = products[0][1:]
    elif products:
        ambiguities.append("conflicting_products")
    for category in ("TOPS", "ACCESSORIES"):
        if re.search(r"\b" + category + r"\b", text, re.I):
            if out["category"] and out["category"] != category:
                ambiguities.append("conflicting_category")
            out["category"] = category
    quantities = re.findall(r"(?<![\w.-])(-?\d+(?:\.\d+)?)\s*(?:pieces?\b|units?\b|件|" +
                             "|".join(PRODUCTS) + r")", text, re.I)
    if quantities:
        out["pieces"] = number(quantities[0])
        if len(set(quantities)) > 1:
            ambiguities.append("conflicting_pieces")
    # Explicit customer clauses; product/customer values never come from orders.csv.
    customer = re.search(r"\bcustomer\s*[:=]\s*([^,;.\n]+)", text, re.I)
    if not customer:
        customer = re.search(r"\bfor\s+([A-Z][A-Za-z &']+?)(?=,|\.|;|\s+(?:due|by|with|using)\b|$)", text)
    if customer and not re.search(r"\b(?:the|workshop|shop|speed|cost)\b", customer.group(1), re.I):
        out["customer"] = customer.group(1).strip()
    for field, prefix in (("order_date", r"(?:order[ _]date|ordered(?: on)?)"),
                          ("due_date", r"(?:due(?:[ _]date)?(?: on| by)?|by|back by|deadline|ship(?: date)?|make|交期|截止)")):
        matches = re.findall(prefix + r"\s*[:=]?\s*(\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,?\s+\d{4})?)", text, re.I)
        dates = []
        for value in matches:
            try:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    normalized = date.fromisoformat(value)
                else:
                    parts = value.replace(",", "").split()
                    month = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(parts[0][:3].lower()) + 1
                    normalized = date(int(parts[2]) if len(parts) == 3 else reference_date.year, month, int(parts[1]))
                dates.append(normalized.isoformat())
            except ValueError:
                ambiguities.append("invalid_date")
        if dates:
            out[field] = dates[0]
            if len(set(dates)) > 1:
                ambiguities.append("conflicting_" + field)
    if re.search(r"\b(next (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|tomorrow|today|next week)\b|明天|下周", low):
        # Only deadline expressions are unresolved, not 'send it today'.
        if re.search(r"(?:due|by|back|deadline|need it|截止|交期).*(?:tomorrow|today|next|明天|下周)", low):
            ambiguities.append("relative_due_date")
    if re.search(r"will confirm|details to follow|date.*moved|usual quantities", low):
        ambiguities.append("unconfirmed_details")
    cost_ignored = bool(re.search(r"cost (?:doesn't|does not) matter|cost is not important|ignore cost|成本不重要", low))
    cheap = bool(re.search(r"cheap(?:est)?|cheepest|lowest cost|min(?:imum)?[ _]cost|最便宜|最低成本", low))
    speed = bool(re.search(r"fast(?:est)?|quick(?:est)?|earliest|speed|asap|urgent|min[ _]delay|最快|优先速度", low))
    quality = bool(re.search(r"lowest defect|min(?:imum)?[ _]defects?|quality first|best quality|最低缺陷", low))
    objectives = (["min_cost"] if cheap else []) + (["min_delay"] if speed else []) + (["min_defects"] if quality else [])
    if re.search(r"\bhybrid\b|balance.*(?:speed|quality)", low):
        objectives = ["hybrid"]
    if cheap and cost_ignored:
        ambiguities.append("conflicting_objective")
    if re.search(r"\bnot (?:the )?(?:cheapest|fastest)|do not prioritize", low):
        objectives = []
        ambiguities.append("negated_objective")
    if len(objectives) > 1:
        ambiguities.append("conflicting_objective")
    elif objectives and not (cheap and cost_ignored):
        out["objective"] = objectives[0]
    max_patterns = [r"(?:at most|no more than|max(?:imum)?|最多|不超过)\s*(?:workshops?\s*[:=]?\s*)?(" + NUMBER + r")\s*(?:workshops?|shops?|工坊|家)",
                    r"(?:across|over|use|using|only)\s+(" + NUMBER + r")\s+(?:workshops?|shops?)", r"max workshops?\s*[:=]\s*(" + NUMBER + r")"]
    limits = [number(m.group(1)) for p in max_patterns for m in re.finditer(p, text, re.I)]
    if re.search(r"single workshop|one workshop only|no split|do not split", low):
        limits.append(1)
    if limits:
        out["num_workshop_allowed"] = limits[0]
        if len(set(limits)) > 1:
            ambiguities.append("conflicting_workshop_limit")
    mentions = workshop_mentions(text)
    last_end = 0
    previous_excluded = False
    for start, end, wid in mentions:
        prefix = text[last_end:start].lower()
        suffix = text[end:end+25].lower()
        excluded = bool(re.search(r"exclude|excluding|avoid|do not use|don't use|not (?:to |use )?$|away from|nothing new to|排除|不用|不要用", prefix))
        excluded |= previous_excluded and bool(re.fullmatch(r"[\s,]*(?:and|or)?[\s,]*", prefix))
        if re.search(r"do not exclude|don't exclude|not excluding", prefix):
            ambiguities.append("negated_exclusion")
            excluded = False
        if excluded:
            out["exclusion"].append(wid)
        elif re.search(r"(?:\bto|\buse|\bonly|\bat|\busing|分配给)\s*$", prefix) or re.match(r"\s+for\b", suffix) or re.search(r"give them|to them", low):
            if out["preferred_workshop"] and out["preferred_workshop"] != wid:
                ambiguities.append("multiple_preferred_workshops")
            out["preferred_workshop"] = wid
        else:
            ambiguities.append("unclear_workshop_constraint")
        last_end, previous_excluded = end, excluded
    out["exclusion"] = sorted(set(out["exclusion"]))
    out["deadline_required"] = bool(re.search(r"must (?:arrive|finish|deliver)|must.*by|can still make|on time|不能迟|必须.*(?:交|完成)", low))
    if re.search(r"\b(?:exactly|budget|cost cap|less than \d|under \d|at least)\b", low):
        ambiguities.append("unsupported_constraint")
    if re.search(r"\bto\s+[A-Z][A-Za-z]+(?:\s+(?:workshop|shop))?\s*[.!?]?$", text) and not mentions:
        ambiguities.append("unknown_workshop_name")
    unsupported = re.search(r"\bcancel\b|\bdelete\b|last october|what price|which workshop did|weather|write (?:a |me )|ignore.*instructions|取消订单|do not allocate|don't allocate|do not send|never send", low)
    if unsupported or not text.strip():
        out["parse_status"] = "invalid"
        ambiguities.append("unsupported_intent")
    else:
        if not out["order_id"]:
            out["missing_fields"] = ["order_id"]
        out["parse_status"] = "needs_clarification" if out["missing_fields"] or ambiguities else "ok"
    out["ambiguities"] = sorted(set(ambiguities))
    return out
