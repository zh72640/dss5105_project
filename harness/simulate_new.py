"""
simulate.py — the shared evaluation harness for Track 2 (subcontractor allocation).

Every team runs its allocator through this file, so the numbers in your report are
comparable with everybody else's. The whole thing is ~180 lines — read it once and
you will understand exactly how your system is being scored.

WHAT IT DOES

It replays the orders in data/orders.csv, one by one in date order, and asks your
allocator to choose a workshop for each. Each workshop behaves according to its
profile card in data/workshops.csv:

    * it can only make what it is equipped for (`makes` vs the order's `category`)
    * it may be unavailable (`status` = SUSPENDED) or capped (`max_batch_pieces`)
    * it processes `capacity_pieces_per_day` pieces per day, first come first served,
      and it starts the run already holding `current_queue_days` of work
    * a batch also costs `pickup_lead_days` for transport
    * with probability `defect_rate` the batch comes back defective and half of it
      is redone (more delay)
    * each piece costs `cost_per_piece`

Choosing a workshop that cannot take the batch is an error, not a bad score — your
system is expected to check capability, capacity and eligibility before it commits,
exactly like a real dispatcher. The helper `eligible_workshops()` below is the rule,
and you may call it from your own code.

HOW TO USE IT

    from simulate import Simulator, eligible_workshops

    def my_allocator(batch, workshops, queues):
        # batch:     {"order_id", "category", "pieces", "sent_date", "due_date"}
        # workshops: {workshop_id: Workshop}  (see the dataclass below)
        # queues:    {workshop_id: days of work currently in its queue}
        candidates = eligible_workshops(batch, workshops)
        return candidates[0].workshop_id     # your logic here

    sim = Simulator()
    sim.run(my_allocator, name="my_policy")
    sim.report()

Run this file directly to see the three baseline policies you have to beat:

    python simulate.py

Add --shock to close a random workshop for two weeks mid-run (for the
robustness objective):

    python simulate.py --shock

The simulator is deterministic (seeded), so everyone sees the same numbers.
"""

import argparse
import csv
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"

"""
That message is the decision, and everything behind it lives in one dispatcher's head. Because for every
workshop, three questions must be answered before a batch can go there:

1. Can they make it? Not every workshop is equipped for every product — some do knitted tops, some do
accessories, some both ( makes in workshops.csv ).
2. Can they take it now? Capacity is per day, and every workshop is already holding a queue of work. A
workshop that is "fast" but three days deep in backlog is not fast today.
3. Are they allowed to take it? One workshop is suspended after a quality audit; another is new and on
trial, capped at small batches ( status and max_batch_pieces ).
Get any of the three wrong and the batch bounces back a day later — in a ten-day cycle, that is the margin
gone.

Goal: Build the system that answers those three questions instantly, makes the allocation, and leaves behind
what the group chat never did: the decision and its reasoning, on record.

"""
##### NEW #####

@dataclass
class Workshop:
    workshop_id: str
    name: str
    capacity: int        # pieces per day
    lead_days: int       # pickup + delivery overhead
    defect_rate: float   # chance a batch comes back defective
    cost: float          # per piece
    makes: set           # product categories it is equipped for
    status: str          # ACTIVE or SUSPENDED
    max_batch: int       # max pieces per batch (None = no cap)
    queue0: float        # days of work already in hand at the start of the run
    notes: str
            
    def get_lateness_score(self, batch, queue):
        eta = batch["pieces"] / self.capacity + self.lead_days + queue[self.workshop_id]
        allowed_days = (batch["due_date"] - batch["sent_date"]).days
        lateness_score = eta - allowed_days if self.status == "ACTIVE" else 10000
        return lateness_score


    def get_defect_score(self, batch):
        return self.defect_rate * batch["pieces"] / self.capacity if self.status == "ACTIVE" else 10000        


    def get_hybrid_score(self, batch, queue):
        lateness_score = self.get_lateness_score(batch, queue)
        defect_score = self.get_defect_score(batch)

        hybrid_score = defect_score if lateness_score <= 0 else 10000
        return hybrid_score


def eligible_workshops(batch, workshops):
    """The three questions a dispatcher asks: can they make it, are they allowed
    to take work, and is the batch within their limit. Returns a list of Workshops."""
    out = []
    for w in workshops.values():
        if w.status != "ACTIVE":
            continue
        if batch["category"] not in w.makes:
            continue
        if w.max_batch is not None and batch["pieces"] > w.max_batch:
            continue
        out.append(w)
    return out

##### END #####



def load_workshops():
    with open(DATA / "workshops.csv", encoding="utf-8") as f:
        return {
            r["workshop_id"]: Workshop(
                r["workshop_id"], r["name"], int(r["capacity_pieces_per_day"]),
                int(r["pickup_lead_days"]), float(r["defect_rate"]),
                float(r["cost_per_piece"]), set(r["makes"].split("+")),
                r["status"],
                int(r["max_batch_pieces"]) if r["max_batch_pieces"] else None,
                float(r["current_queue_days"]), r["notes"]
            )
            for r in csv.DictReader(f)
        }


def load_batches():
    with open(DATA / "orders.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    batches = [
        {
            "order_id": r["order_id"],
            "category": r["category"],
            "pieces": int(r["pieces"]),
            "sent_date": date.fromisoformat(r["order_date"]),
            "due_date": date.fromisoformat(r["due_date"]),
        }
        for r in rows
    ]
    batches.sort(key=lambda b: b["sent_date"])
    return batches


class Simulator:
    def __init__(self, shock=False, seed=5105):
        self.workshops = load_workshops()
        self.batches = load_batches()
        self.shock = shock
        self.seed = seed
        self.results = {}   # name -> list of per-batch outcomes

    def run(self, allocator, name):
        rng = random.Random(self.seed)
        day0 = self.batches[0]["sent_date"]
        # queue_free[w] = day number when the workshop finishes everything it holds
        queue_free = {w_id: w.queue0 for w_id, w in self.workshops.items()}

        shock_target, shock_start, shock_end = None, 30, 44
        if self.shock:
            shock_target = rng.choice(
                [w.workshop_id for w in self.workshops.values() if w.status == "ACTIVE"])

        outcomes = []
        for batch in self.batches:
            day = (batch["sent_date"] - day0).days            
            queues = {w: max(0.0, queue_free[w] - day) for w in self.workshops}            
            choice = allocator(dict(batch), self.workshops, queues)            

            ok = {w.workshop_id for w in eligible_workshops(batch, self.workshops)}
            if choice not in ok:
                w = self.workshops.get(choice)
                reason = "unknown workshop" if w is None else (
                    f"status={w.status}" if w.status != "ACTIVE"
                    else f"cannot make {batch['category']}" if batch["category"] not in w.makes
                    else f"batch of {batch['pieces']} exceeds its {w.max_batch}-piece limit")
                raise ValueError(
                    f"{name}: {choice} cannot take {batch['order_id']} ({reason}). "
                    "Check eligible_workshops() before committing.")

            w = self.workshops[choice]
            start = max(day, queue_free[choice])
            if shock_target == choice and shock_start <= start <= shock_end:
                start = float(shock_end)          # closed: work waits until it reopens
            work_days = batch["pieces"] / w.capacity
            defective = rng.random() < w.defect_rate
            if defective:
                work_days *= 1.5                  # half the batch is redone
            queue_free[choice] = start + work_days

            done_day = start + work_days + w.lead_days
            done_date = day0 + timedelta(days=round(done_day))
            outcomes.append({
                "workshop": choice,
                "pieces": batch["pieces"],
                "turnaround": done_day - day,
                "late": done_date > batch["due_date"],
                "late_days": max(0, (done_date - batch["due_date"]).days),
                "defective": defective,
                "cost": batch["pieces"] * w.cost,
            })
        self.results[name] = outcomes
        return outcomes

    def metrics(self):
        """name -> (mean days, p90 days, % late, avg late days, % defect, cost, max share)"""
        res = {}
        for name, out in self.results.items():
            days = sorted(o["turnaround"] for o in out)
            n = len(out)
            mean = sum(days) / n
            p90 = days[int(0.9 * n)]
            late = 100 * sum(o["late"] for o in out) / n
            late_orders = [o["late_days"] for o in out if o["late"]]
            avg_late_days = sum(late_orders) / len(late_orders) if late_orders else 0
            defect = 100 * sum(o["defective"] for o in out) / n
            cost = sum(o["cost"] for o in out)
            pieces = sum(o["pieces"] for o in out)
            by_w = {}
            for o in out:
                by_w[o["workshop"]] = by_w.get(o["workshop"], 0) + o["pieces"]
            share = 100 * max(by_w.values()) / pieces
            res[name] = (mean, p90, late, avg_late_days, defect, cost, share)
        return res

    def report(self, metrics=None):
        metrics = metrics or self.metrics()
        header = f"{'policy':<24}{'mean days':>10}{'p90 days':>10}{'% late':>8}{'avg late days':>14}{'% defect':>10}{'cost':>12}{'max share':>11}"
        print(header)
        print("-" * len(header))
        for name, (mean, p90, late, avg_late_days, defect, cost, share) in metrics.items():
            print(f"{name:<24}{mean:>10.2f}{p90:>10.2f}{late:>7.2f}%{avg_late_days:>14.2f}{defect:>9.2f}%{cost:>12,.0f}{share:>10.2f}%")


# ------------------------- the three baselines to beat -------------------------
# Note that even the dumbest baseline checks eligibility first. So must you.

def random_choice(batch, workshops, queues):
    """Picks any eligible workshop at random. If you cannot beat this, something is wrong."""
    ok = eligible_workshops(batch, workshops)
    # print(ok)
    # print()
    return random.Random(batch["order_id"]).choice(ok).workshop_id


def greedy_biggest(batch, workshops, queues):
    """Always the highest-capacity eligible workshop. Watch what the queue does to it."""
    ok = eligible_workshops(batch, workshops)
    return max(ok, key=lambda w: w.capacity).workshop_id


def cheapest(batch, workshops, queues):
    """Always the cheapest eligible workshop. Great cost, and look at everything else."""
    ok = eligible_workshops(batch, workshops)
    return min(ok, key=lambda w: w.cost).workshop_id


def minimum_lateness(batch, workshops, queues):
    """Always the eligible workshop with the minimum estimated lateness."""
    ok = eligible_workshops(batch, workshops)
    return min(ok, key=lambda w: w.get_lateness_score(batch, queues)).workshop_id


def minimum_defect(batch, workshops, queues):
    """Always the eligible workshop with the minimum estimated defect score."""
    ok = eligible_workshops(batch, workshops)
    return min(ok, key=lambda w: w.get_defect_score(batch)).workshop_id


def hybrid(batch, workshops, queues):
    """Always the eligible workshop with the minimum estimated hybrid score."""
    ok = eligible_workshops(batch, workshops)
    return min(ok, key=lambda w: w.get_hybrid_score(batch, queues)).workshop_id

def weighted_hybrid_score(batch, workshops, queues, w_late=0.8, w_defect=0.2):
    """Weighted mix of lateness (80%) and defect (20%) scores, each min-max scaled to 0-1
    across the eligible workshops so they are on a common scale."""
    ok = eligible_workshops(batch, workshops)
    late = [w.get_lateness_score(batch, queues) for w in ok]
    defect = [w.get_defect_score(batch) for w in ok]

    def scale(vals):
        lo, hi = min(vals), max(vals)
        return [0.0 if hi == lo else (v - lo) / (hi - lo) for v in vals]

    scores = [w_late * l + w_defect * d for l, d in zip(scale(late), scale(defect))]
    return ok[scores.index(min(scores))].workshop_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shock", action="store_true",
                        help="close a random workshop for two weeks mid-run")
    parser.add_argument("--multi", action="store_true",
                        help="run 10 times with different random seeds and print the averaged metrics")
    args = parser.parse_args()

    policies = [
        (random_choice, "random"),
        (greedy_biggest, "greedy_biggest"),
        (cheapest, "cheapest"),
        (minimum_lateness, "minimum_lateness"),
        (minimum_defect, "minimum_defect"),
        # (hybrid, "hybrid"),
        (weighted_hybrid_score, "weighted_hybrid"),
    ]

    if args.multi:
        n_runs = 10
        seeds = [5105 + i for i in range(n_runs)]
        total = {}
        for seed in seeds:
            sim = Simulator(shock=args.shock, seed=seed)
            for fn, name in policies:
                sim.run(fn, name)
            for name, vals in sim.metrics().items():
                acc = total.setdefault(name, [0.0] * len(vals))
                for i, v in enumerate(vals):
                    acc[i] += v
        print(f"Average over {n_runs} runs (seeds {seeds[0]}-{seeds[-1]})")
        sim.report({name: tuple(v / n_runs for v in acc) for name, acc in total.items()})
    else:
        sim = Simulator(shock=args.shock)
        for fn, name in policies:
            sim.run(fn, name)
        sim.report()
