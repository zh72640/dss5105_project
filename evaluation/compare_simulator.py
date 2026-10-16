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
OBJECTIVES = ("min_delay", "min_defects", "hybrid", "min_cost")


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
              ("harness/simulate.py", "data/orders.csv", "data/workshops.csv", "app/allocator/planner.py", "evaluation/simulator_adapter.py")}
    return {"schema_version": "simulator_comparison_v1", "seeds": list(seeds), "source_sha256": hashes,
            "primary_setting": "min_delay (existing default; team objective assignment pending confirmation)",
            "hybrid_score": "0.6 * estimated_days + 0.4 * expected_defect_rate * 100",
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
    lines = ["# 官方模拟器对比结果", "", "固定 seed、原始 120 订单、原样官方 harness。所有指标越低越好；max share 仅衡量集中程度，不等于已实现公平性优化。", "",
             "默认主设置 min_delay 来自现有系统；团队课程主目标分配尚待确认。以下是开发集实验，不是独立 holdout 或真实经营收益。", "",
             "| 场景 | Seed | 策略 | 平均天数 | P90天数 | 迟交% | 缺陷% | 成本 | 最大份额% |",
             "|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for run in report["runs"]:
        m = run["metrics"]
        lines.append(f"| {run['scenario']} | {run['seed']} | {run['policy']} | " + " | ".join(f"{m[k]:.2f}" for k in METRICS) + " |")
    lines += ["", "## 基线胜出的指标", "", "每个设置对三种基线逐项比较，差异不代表统计显著性；完整逐订单结果在同目录 JSON。", ""]
    for row in report["comparisons"]:
        if row["baseline_wins"]:
            lines.append(f"- {row['scenario']} / seed {row['seed']} / {row['policy']}：{row['baseline']} 在 {', '.join(row['baseline_wins'])} 更低。")
    lines += ["", "## 10 个可复核的不利案例", "", "取主设置在固定 seed 下的前 10 个不同订单损失案例，保留完整数值，不据此调整策略。这里只是算法比较，不代替最终要求的全部系统失败分析。", ""]
    seen = set()
    for row in report["primary_per_order_losses"]:
        if row["order_id"] in seen:
            continue
        seen.add(row["order_id"])
        ours, theirs = row["planner"], row["baseline_outcome"]
        lines.append(f"- {row['order_id']}（{row['scenario']}，seed {row['seed']}）对比 {row['baseline']}："
                     f"本系统 {ours['workshop']} / {ours['turnaround']:.2f} 天 / 成本 {ours['cost']:.2f}；"
                     f"基线 {theirs['workshop']} / {theirs['turnaround']:.2f} 天 / 成本 {theirs['cost']:.2f}。"
                     f"较差项：{', '.join(row['worse_metrics'])}。"
                     + ("速度目标未约束总成本，因此可能选择更贵工坊。" if "cost" in row["worse_metrics"] else
                        "应结合不同历史队列、随机返工与冲击核查；单条结果不能证明局部选择错误。"))
        if len(seen) == 10:
            break
    lines += ["", "## 解释边界", "", "混合分数为 `0.6 × 天数 + 0.4 × 缺陷率百分数`，权重沿用现有实现，未据本次结果调参。"
              "min_delay 是预计周转时间目标，不等于全局最少迟交。官方只接收单工坊选择；拆单收益另行测量。"
              "冲击对象不传入 allocator，不能声称策略能预知工坊故障。官方 shock 选择会额外消耗一次随机数，"
              "因此同 seed 的 standard/shock 返工样本也会不同；场景差值不能解释为纯停工效应。", "",
              "系统相对简短启发式增加的能力：自然语言校验、约束执行、多轮澄清、可追溯分配、事务与生产生命周期；这些能力需由接口和可靠性测试证明，不能由模拟器分数替代。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluation/results")
    parser.add_argument("--seeds", type=int, nargs="+", default=[5105])
    args = parser.parse_args()
    report = compare(tuple(dict.fromkeys(args.seeds)))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "simulator_comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.output_dir / "simulator_comparison_CN.md").write_text(markdown(report))
    print(json.dumps({"runs": len(report["runs"]), "baseline_comparisons": len(report["comparisons"]),
                      "primary_loss_cases": len(report["primary_per_order_losses"]), "output_dir": str(args.output_dir)}, indent=2))


if __name__ == "__main__":
    main()
