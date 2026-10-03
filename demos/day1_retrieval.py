"""Day 1 trace, with the complete Week 6 result for downstream inspection."""
import json
from app.pipeline import process_request

if __name__ == "__main__":
    result = process_request("Please allocate ORD-045 with the lowest cost.", backend="offline")
    print(json.dumps({"request_id": result["request_id"], "parsed": result["parsed"],
                      "order": result["trace"].get("order"), "workshop_count": result["trace"].get("workshop_count"),
                      "result": result["result"]}, indent=2))
