"""Week 5 explicit mock chain, completely separate from Week 6 repositories."""
import argparse
import json
from app.agent.parser import parse_with_telemetry

MESSAGES = ["Allocate ORD-045 cheapest; exclude W3; at most two workshops.",
            "Please allocate the urgent order.", "Cancel order ORD-045.",
            "ORD-045: cost doesn't matter, prioritize speed.",
            "Allocate ORD-045 cheapest, but cost does not matter."]


def handle_message(message, backend="offline"):
    outcome = parse_with_telemetry(message, [], backend=backend)
    result = {"mock": True, "raw_message": message,
              "parser_output": outcome.parsed.to_dict() if outcome.parsed else None,
              "validation_status": outcome.telemetry["validation_result"], "telemetry": outcome.telemetry}
    if not outcome.parsed or outcome.parsed.parse_status != "ok":
        return {**result, "mock_result": "STOPPED_BEFORE_RETRIEVAL"}
    order = {"order_id": outcome.parsed.order_id, "pieces": 150, "category": "TOPS"}
    workshops = ["W1", "W2", "W3"]
    eligible = [w for w in workshops if w not in outcome.parsed.exclusion]
    return {**result, "mock_order": order, "mock_workshops": workshops,
            "mock_result": {"workshop_id": eligible[0], "pieces": order["pieces"]}}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--backend", choices=["offline", "llm"], default="offline")
    args = parser.parse_args()
    for i, message in enumerate(MESSAGES, 1):
        print(json.dumps({"request_id": f"week5-demo-{i}", **handle_message(message, args.backend)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
