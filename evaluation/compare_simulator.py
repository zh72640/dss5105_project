"""Reproducible policy comparison, retaining losses and every batch outcome."""
import argparse
import hashlib
import json
from pathlib import Path

from evaluation.simulator_adapter import make_allocator
from harness.simulate import Simulator, cheapest, greedy_biggest, random_choice

ROOT = Path(__file__).resolve().parents[1]
METRICS = ("mean_days", "p90_days", "late_percent", "defect_percent", "total_cost", "max_share_percent")
BASELINES = {"random": random_choice, "greedy_biggest": greedy_biggest, "cheapest": cheapest}
OBJECTIVES = ("min_delay", "min_defects", "hybrid", "min_cost", "weighted_hybrid")


def summarize(outcomes):
    if not outcomes:
        raise ValueError("empty evaluation")
    n = len(outcomes)
    days = sorted(row["turnaround"] for row in outcomes)
    by_workshop = {}
    for row in outcomes:
        by_workshop[row["workshop"]] = by_workshop.get(row["workshop"], 0) + row["pieces"]
    return {"batches": n, "mean_days": sum(days) / n, "p90_days": days[int(.9 * n)],
            "late_percent": 100 * sum(r["late"] for r in outcomes) / n,
            "defect_percent": 100 * sum(r["defective"] for r in outcomes) / n,
            "total_cost": sum(r["cost"] for r in outcomes),
            "max_share_percent": 100 * max(by_workshop.values()) / sum(by_workshop.values())}


def compare(seeds=(5105,)):
    policies = {**BASELINES, **{f"planner_{o}": make_allocator(o) for o in OBJECTIVES}}
    runs, losses, comparisons = [], [], []
    for seed in seeds:
        for shock in (False, True):
            sim = Simulator(shock=shock, seed=seed)
            scenario = "shock" if shock else "standard"
            for name, allocator in policies.items():
                outcomes = sim.run(allocator, name)
                runs.append({"seed": seed, "scenario": scenario, "policy": name, "metrics": summarize(outcomes),
                             "outcomes": [{"order_id": b["order_id"], **r} for b, r in zip(sim.batches, outcomes)]})
            for objective in OBJECTIVES:
                name = "planner_" + objective
                ours = summarize(sim.results[name])
                for baseline in BASELINES:
                    theirs = summarize(sim.results[baseline])
                    comparisons.append({"seed": seed, "scenario": scenario, "policy": name, "baseline": baseline,
                                        "baseline_wins": [m for m in METRICS if theirs[m] < ours[m] - 1e-9],
                                        "planner_wins": [m for m in METRICS if ours[m] < theirs[m] - 1e-9],
                                        "ties": [m for m in METRICS if abs(ours[m] - theirs[m]) <= 1e-9]})
            # Preserve all per-order primary-policy losses; they are not independent
            # counterfactuals because each policy creates a different preceding queue.
            for baseline in BASELINES:
                for batch, ours, theirs in zip(sim.batches, sim.results["planner_min_delay"], sim.results[baseline]):
                    worse = [m for m in ("turnaround", "late", "defective", "cost") if ours[m] > theirs[m]]
                    if worse:
                        losses.append({"seed": seed, "scenario": scenario, "baseline": baseline,
                                       "order_id": batch["order_id"], "worse_metrics": worse,
                                       "planner": ours, "baseline_outcome": theirs})
    hashes = {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in
              ("harness/simulate.py", "data/orders.csv", "data/workshops.csv", "app/allocator/planner.py", "app/allocator/strategies.py", "evaluation/simulator_adapter.py")}
    return {"schema_version": "simulator_comparison_v1", "seeds": list(seeds), "source_sha256": hashes,
            "primary_setting": "min_delay (existing default; team objective assignment pending confirmation)",
            "hybrid_score": "0.6 * estimated_days + 0.4 * expected_defect_rate * 100",
            "weighted_hybrid_score": "0.8 * minmax(signed lateness) + 0.2 * minmax(defect_rate * pieces / capacity), single workshop only",
            "limitations": ["Single-workshop adapter; split plans are not evaluated by the official API.",
                            "min_delay minimizes estimated turnaround, not the global count of late orders.",
                            "Fixed development dataset, not a held-out experiment; no tuning performed by this script.",
                            "Shock target is hidden from allocators; current implementation does not predict outages.",
                            "Official shock selection consumes a random draw, so standard/shock defect samples differ even with the same seed.",
                            "Calendar-day simulator and round() delivery dates differ from UI ceil() dates.",
                            "Per-order losses include policy-induced queue differences, not causal counterfactuals.",
                            "Hybrid weights mix days and defect percentage points; they are heuristic, not business-calibrated."],
            "runs": runs, "comparisons": comparisons, "primary_per_order_losses": losses}


def markdown(report):
    lines = ["# Simulator comparison", "", "Fixed seeds, the original 120 orders, and the supplied simulation harness. Lower metrics are better; maximum share measures concentration, not an implemented fairness objective.", "",
             "The primary min_delay setting follows the existing default. The course objective assignment remains to be confirmed. These are development-data observations, not holdout performance or realized business gains.", "",
             "| Scenario | Seed | Policy | Mean days | P90 days | Late % | Defect % | Cost | Max share % |",
             "|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for run in report["runs"]:
        m = run["metrics"]
        lines.append(f"| {run['scenario']} | {run['seed']} | {run['policy']} | " + " | ".join(f"{m[k]:.2f}" for k in METRICS) + " |")
    lines += ["", "## Metrics where baselines win", "", "Each setting is compared with three baselines. Differences do not establish statistical significance. The adjacent JSON retains all order-level outcomes.", ""]
    for row in report["comparisons"]:
        if row["baseline_wins"]:
            lines.append(f"- {row['scenario']} / seed {row['seed']} / {row['policy']}: {row['baseline']} is lower on {', '.join(row['baseline_wins'])}.")
    lines += ["", "## Ten inspectable loss cases", "", "The first ten distinct losing orders for the primary setting are retained with their values; policies are not tuned from these cases. This algorithm comparison does not replace system failure analysis.", ""]
    seen = set()
    for row in report["primary_per_order_losses"]:
        if row["order_id"] in seen:
            continue
        seen.add(row["order_id"])
        ours, theirs = row["planner"], row["baseline_outcome"]
        lines.append(f"- {row['order_id']} ({row['scenario']}, seed {row['seed']}) against {row['baseline']}: "
                     f"planner {ours['workshop']} / {ours['turnaround']:.2f} days / cost {ours['cost']:.2f}; "
                     f"baseline {theirs['workshop']} / {theirs['turnaround']:.2f} days / cost {theirs['cost']:.2f}. "
                     f"Worse metrics: {', '.join(row['worse_metrics'])}. "
                     + ("The speed objective does not cap cost and can select a more expensive workshop." if "cost" in row["worse_metrics"] else
                        "Inspect preceding queues, random rework, and shocks; one outcome cannot prove the local choice was wrong."))
        if len(seen) == 10:
            break
    lines += ["", "## Interpretation limits", "", "Hybrid uses `0.6 * days + 0.4 * defect percentage`; existing weights are not tuned on these results. "
              "min_delay minimizes estimated turnaround, not global late-order count. The supplied simulator accepts one workshop; split benefits need separate measurement. "
              "Allocators cannot see the shock target or predict outages. Shock selection consumes an extra random draw, "
              "so identical seeds can produce different rework samples across scenarios; their difference is not a pure downtime effect.", "",
              "Natural-language validation, constraint enforcement, clarification, audit, transactions, and lifecycle behavior require interface and reliability tests. Simulator scores do not establish those capabilities.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluation/results")
    parser.add_argument("--seeds", type=int, nargs="+", default=[5105])
    args = parser.parse_args()
    report = compare(tuple(dict.fromkeys(args.seeds)))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "simulator_comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.output_dir / "simulator_comparison.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"runs": len(report["runs"]), "baseline_comparisons": len(report["comparisons"]),
                      "primary_loss_cases": len(report["primary_per_order_losses"]), "output_dir": str(args.output_dir)}, indent=2))


if __name__ == "__main__":
    main()
