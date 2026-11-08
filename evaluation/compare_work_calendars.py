"""Evaluate unchanged single-workshop policies with Sunday production closures.

This is an evaluation-only extension. The official simulator and application are
unchanged. Run with ``python3 -m evaluation.compare_work_calendars --output-dir ...``.
"""
import argparse
import hashlib
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

from evaluation.compare_simulator import BASELINES, OBJECTIVES, summarize
from evaluation.simulator_adapter import make_allocator
from harness.simulate import Simulator, eligible_workshops


ROOT = Path(__file__).resolve().parents[1]


class ProductionCalendar:
    """Fractional production days; transportation is outside this calendar."""

    def __init__(self, origin: date, sunday_off: bool):
        self.origin = origin
        self.sunday_off = sunday_off

    def closed(self, day: int) -> bool:
        return self.sunday_off and (self.origin.weekday() + day) % 7 == 6

    def working_time(self, start: float, end: float) -> float:
        """Production capacity available in [start, end), in working days."""
        if end <= start:
            return 0.0
        if not self.sunday_off:
            return end - start
        total = 0.0
        cursor = start
        while cursor < end:
            day = math.floor(cursor)
            boundary = min(end, day + 1.0)
            if not self.closed(day):
                total += boundary - cursor
            cursor = boundary
        return total

    def finish(self, start: float, working_days: float) -> float:
        """Consume production work, pausing throughout each closed day."""
        if working_days < 0 or not math.isfinite(working_days):
            raise ValueError("working_days must be finite and nonnegative")
        if not self.sunday_off or working_days == 0:
            return start + working_days
        cursor = start
        remaining = working_days
        while remaining > 0:
            day = math.floor(cursor)
            boundary = day + 1.0
            if not self.closed(day):
                available = boundary - cursor
                if remaining <= available + 1e-12:
                    # Arithmetic noise must not turn a Saturday boundary into
                    # an additional full Sunday of waiting.
                    return min(cursor + remaining, boundary)
                remaining -= available
            cursor = boundary
        return cursor


def simulate(allocator, *, sunday_off: bool, seed: int):
    """Replay the official inputs with a different production calendar only.

    Queue inputs remain outstanding production days, not elapsed calendar days.
    The existing allocator is not made calendar-aware by this experiment.
    """
    source = Simulator(shock=False, seed=seed)
    origin = source.batches[0]["sent_date"]
    calendar = ProductionCalendar(origin, sunday_off)
    rng = random.Random(seed)
    free = {wid: calendar.finish(0.0, w.queue0) for wid, w in source.workshops.items()}
    outcomes = []
    for batch in source.batches:
        day = (batch["sent_date"] - origin).days
        queues = {wid: calendar.working_time(day, end) for wid, end in free.items()}
        choice = allocator(dict(batch), source.workshops, queues)
        if choice not in {w.workshop_id for w in eligible_workshops(batch, source.workshops)}:
            raise ValueError(f"Ineligible allocation: {batch['order_id']} -> {choice}")
        workshop = source.workshops[choice]
        start = max(float(day), free[choice])
        work = batch["pieces"] / workshop.capacity
        defective = rng.random() < workshop.defect_rate
        if defective:
            work *= 1.5
        free[choice] = calendar.finish(start, work)
        done = free[choice] + workshop.lead_days
        delivery = origin + timedelta(days=round(done))
        outcomes.append({
            "order_id": batch["order_id"], "workshop": choice, "pieces": batch["pieces"],
            "turnaround": done - day, "late": delivery > batch["due_date"],
            "defective": defective, "cost": batch["pieces"] * workshop.cost,
        })
    return outcomes


def assert_official_reproduction(actual, expected):
    if len(actual) != len(expected):
        raise AssertionError("Official reproduction changed the order count")
    for row, reference in zip(actual, expected):
        for key, value in reference.items():
            if isinstance(value, float):
                matches = math.isclose(row[key], value, rel_tol=1e-12, abs_tol=1e-10)
            else:
                matches = row[key] == value
            if not matches:
                raise AssertionError(f"Official reproduction differs: {row['order_id']} {key}")


def compare(seed=5105):
    policies = {**BASELINES, **{f"planner_{o}": make_allocator(o) for o in OBJECTIVES}}
    runs = []
    for name, allocator in policies.items():
        reference = Simulator(shock=False, seed=seed).run(allocator, name)
        seven_day = simulate(allocator, sunday_off=False, seed=seed)
        assert_official_reproduction(seven_day, reference)
        for scenario, outcomes in (
            ("seven_day", seven_day),
            ("sunday_off", simulate(allocator, sunday_off=True, seed=seed)),
        ):
            runs.append({"scenario": scenario, "policy": name, "seed": seed,
                         "metrics": summarize(outcomes), "outcomes": outcomes})
    files = ("harness/simulate.py", "data/orders.csv", "data/workshops.csv",
             "app/allocator/planner.py", "evaluation/simulator_adapter.py",
             "evaluation/compare_simulator.py", "evaluation/compare_work_calendars.py")
    return {
        "schema_version": "work_calendar_comparison_v1", "seed": seed,
        "official_reproduction": f"PASS: all {len(policies)} policies and 120 outcomes per policy",
        "assumptions": [
            "Normal scenario only; no additional workshop shock.",
            "Sunday production capacity is zero; Monday through Saturday retain the supplied daily capacity.",
            "Initial queue values denote outstanding production working days in both scenarios.",
            "Transport lead times remain calendar days, including Sundays.",
            "Order arrival dates and contractual due dates are unchanged.",
            "Fractional production time and the official round() delivery-date rule are retained.",
            "Existing policies are unchanged and receive remaining production workdays as queue inputs.",
            "Planner ETA scoring is not calendar-aware; this measures existing policies in a changed environment.",
            "One workshop per order; no splitting or rescheduling of previously assigned orders.",
            "Same original development data and one random seed; no statistical or real-provider claim.",
        ],
        "source_sha256": {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in files},
        "runs": runs,
    }


def markdown(report):
    lines = ["# Sunday production closure experiment", "",
             f"Seed: {report['seed']}. All runs cover 120 orders using unchanged single-workshop policies.",
             "", report["official_reproduction"], "", "## Assumptions", ""]
    lines.extend(f"- {item}" for item in report["assumptions"])
    lines.extend(["", "## Results", "",
                  "Defect percentage is the fraction of defective batches, not defective pieces.", "",
                  "| Policy | Calendar | Mean days | P90 days | Late % | Defective batches % | Total cost | Max share % |",
                  "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for row in report["runs"]:
        m = row["metrics"]
        values = " | ".join(f"{m[key]:.2f}" for key in
                            ("mean_days", "p90_days", "late_percent", "defect_percent", "total_cost", "max_share_percent"))
        lines.append(f"| {row['policy']} | {row['scenario']} | {values} |")
    lines.extend(["", "This experiment does not add a production calendar to the running application.",
                  "The original course simulator, application code, databases and earlier reports are unchanged.",
                  "Per-order outcomes and source fingerprints are in results.json.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=5105)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.output_dir / "report.md").write_text(markdown(report))
    print(markdown(report))


if __name__ == "__main__":
    main()
