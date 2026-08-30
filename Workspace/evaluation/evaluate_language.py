"""Week 4 validation of the initial language ground-truth artefact."""
import csv
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    with (HERE / "language_ground_truth.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 30, f"expected 30 requests, found {len(rows)}"
    assert {r["request_id"] for r in rows} == {f"R{i:02d}" for i in range(1, 31)}
    counts = Counter(r["expected_behavior"] for r in rows)
    print("Ground truth rows: 30")
    for behavior, count in sorted(counts.items()):
        print(f"{behavior}: {count}")
    print("Status: initial behaviour labels structurally valid; second human review pending")


if __name__ == "__main__":
    main()

