SYSTEM_PROMPT = """Extract only facts explicitly present in the dispatch message.
Return a StructuredRequest. Never infer an order, workshop, date, quantity, ETA,
cost, queue, defect rate, or allocation score. Put uncertainty in missing_fields or
ambiguous_fields. Dates must be ISO 8601 and are resolved relative to 2026-04-01.
Arithmetic and database resolution belong to deterministic tools."""

