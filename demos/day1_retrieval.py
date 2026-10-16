"""Day 1 trace, with the complete Week 6 result for downstream inspection."""
import json
from app.services.allocation.dispatch import seed_allocation

if __name__ == "__main__":
    result = seed_allocation("Please allocate ORD-045 with the lowest cost.")
    print(json.dumps({"request_id": result["request_id"], "parsed": result["parsed"],
                      "order": result["trace"].get("order"), "workshop_count": result["trace"].get("workshop_count"),
                      "result": result["result"]}, indent=2))
