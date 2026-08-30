import argparse
import json
from pathlib import Path
from .pipeline import process_request

DATA = Path(__file__).resolve().parents[1] / "data" / "dispatch_requests.txt"


def request_text(request_id: str) -> str:
    for line in DATA.read_text(encoding="utf-8").splitlines():
        if line.startswith(request_id + " "):
            return line
    raise SystemExit(f"Unknown request: {request_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", default="R09")
    parser.add_argument("--objective", default="min_lateness",
                        choices=["min_lateness", "min_defects", "min_cost", "hybrid"])
    args = parser.parse_args()
    print(json.dumps(process_request(request_text(args.request), args.objective), indent=2))

