"""Strict shape + deterministic semantic/evidence checks, shared by both backends."""
import json
import re
from datetime import date
from app.schemas.parser_schema import ParseResult, json_schema
from .normalization import PRODUCTS, order_ids, workshop_mentions


class ValidationError(ValueError):
    pass


def validate_output(raw: str, message: str, reference_date=date(2026, 4, 1)) -> ParseResult:
    try:
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValidationError("duplicate_json_key")
                result[key] = value
            return result
        data = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, TypeError) as error:
        raise ValidationError("invalid_json") from error
    schema = json_schema()
    if not isinstance(data, dict) or set(data) != set(schema["properties"]):
        raise ValidationError("schema_fields_mismatch")
    types = {"string": str, "integer": int, "array": list, "boolean": bool, "null": type(None)}
    for name, prop in schema["properties"].items():
        value = data[name]
        allowed = prop["type"] if isinstance(prop["type"], list) else [prop["type"]]
        if type(value) not in [types[k] for k in allowed]:
            raise ValidationError("invalid_type:" + name)
        if "enum" in prop and value not in prop["enum"]:
            raise ValidationError("invalid_enum:" + name)
        if isinstance(value, list) and any(type(v) is not str or not v.strip() for v in value):
            raise ValidationError("invalid_array:" + name)
        if isinstance(value, str) and not value.strip():
            raise ValidationError("empty_string:" + name)
    for field in ("pieces", "num_workshop_allowed"):
        if data[field] is not None and data[field] <= 0:
            # Preserve the rejected raw value only in telemetry, never parsed DB columns.
            return ParseResult(parse_status="invalid", ambiguities=["invalid_" + field])
    for field in ("order_date", "due_date"):
        if data[field] is not None:
            try:
                if date.fromisoformat(data[field]).isoformat() != data[field]:
                    raise ValueError()
            except ValueError as error:
                raise ValidationError("invalid_date:" + field) from error
    if data["order_id"] is not None and data["order_id"] not in order_ids(message):
        raise ValidationError("ungrounded_order_id")
    mentioned = {w[2] for w in workshop_mentions(message)}
    if any(not re.fullmatch(r"W[1-9]\d*", w) or w not in mentioned for w in data["exclusion"]):
        raise ValidationError("ungrounded_exclusion")
    if data["preferred_workshop"] and data["preferred_workshop"] not in mentioned:
        raise ValidationError("ungrounded_preferred_workshop")
    if data["pieces"] is not None and not re.search(r"(?<![\w.-])" + str(data["pieces"]) + r"(?![\w.])", message):
        raise ValidationError("ungrounded_pieces")
    if data["customer"] and data["customer"].casefold() not in message.casefold():
        raise ValidationError("ungrounded_customer")
    if data["product"]:
        patterns = [p for p, (name, _) in PRODUCTS.items() if name == data["product"]]
        if not any(re.search(r"\b" + p + r"\b", message, re.I) for p in patterns):
            if data["product"].casefold() not in message.casefold():
                raise ValidationError("ungrounded_product")
    # Conservative evidence checks for dates, numerical limits and known constraints.
    # Broader LLM language support is allowed, but recognized hard constraints cannot vanish.
    from .rule_parser import extract
    evidence = extract(message, reference_date)
    for field in ("order_date", "due_date"):
        if data[field] and data[field] != evidence[field]:
            raise ValidationError("ungrounded_" + field)
    if data["num_workshop_allowed"] is not None and data["num_workshop_allowed"] != evidence["num_workshop_allowed"]:
        raise ValidationError("ungrounded_num_workshop_allowed")
    for field in ("pieces", "due_date", "order_date", "num_workshop_allowed", "preferred_workshop"):
        if evidence[field] is not None and data[field] != evidence[field]:
            raise ValidationError("dropped_or_changed_constraint:" + field)
    if not set(evidence["exclusion"]).issubset(data["exclusion"]):
        raise ValidationError("dropped_exclusion")
    if data["category"] and data["category"] != evidence["category"]:
        raise ValidationError("ungrounded_category")
    if data["objective"] and not evidence["objective"] and not evidence["ambiguities"]:
        raise ValidationError("ungrounded_objective")
    if evidence["objective"] and data["objective"] != evidence["objective"]:
        raise ValidationError("dropped_or_changed_objective")
    if data["deadline_required"] != evidence["deadline_required"]:
        raise ValidationError("ungrounded_or_dropped_deadline_requirement")
    if evidence["parse_status"] == "invalid":
        data["parse_status"] = "invalid"
    data["ambiguities"].extend(evidence["ambiguities"])
    # Shape compliance is insufficient: code always enforces terminal diagnostics.
    if not data["order_id"] and "order_id" not in data["missing_fields"] and data["parse_status"] != "invalid":
        data["missing_fields"].append("order_id")
    if data["preferred_workshop"] in data["exclusion"]:
        data["ambiguities"].append("preferred_workshop_excluded")
    if data["order_date"] and data["due_date"] and data["order_date"] > data["due_date"]:
        data["ambiguities"].append("due_before_order_date")
    if data["parse_status"] != "invalid" and (data["missing_fields"] or data["ambiguities"]):
        data["parse_status"] = "needs_clarification"
    if data["parse_status"] == "needs_clarification" and not (data["missing_fields"] or data["ambiguities"]):
        data["ambiguities"].append("unspecified_ambiguity")
    for field in ("exclusion", "missing_fields", "ambiguities"):
        data[field] = sorted(set(data[field]))
    return ParseResult(**data)
