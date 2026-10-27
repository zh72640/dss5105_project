"""Schedule orders in workshop production queues without making queued orders late.

Each workshop starts with an empty assigned-order queue. Its initial availability
offset and status are loaded from workshops.csv; day zero is 1 April 2026.
"""

import csv
from datetime import date

from simulate_new import DATA, load_workshops

TODAY = date(2026, 4, 1)


def _load_orders():
    with open(DATA / "orders.csv", encoding="utf-8") as f:
        return {row["order_id"]: row for row in csv.DictReader(f)}


def _load_workshop_settings():
    with open(DATA / "workshops.csv", encoding="utf-8") as f:
        return {row["workshop_id"]: row for row in csv.DictReader(f)}


def _initialize_workshops(workshops):
    """Apply CSV status and initial availability, without resetting assigned queues."""
    settings = _load_workshop_settings()
    for workshop_id, workshop in workshops.items():
        if workshop_id not in settings:
            raise ValueError(f"workshop {workshop_id} is missing from workshops.csv")
        row = settings[workshop_id]
        workshop.status = row["status"]
        if not hasattr(workshop, "production_queue"):
            workshop.production_queue = []
            workshop.available_day = float(row["current_queue_days"])


def _job(row):
    return {
        "order_id": row["order_id"],
        "category": row["category"],
        "pieces": int(row["pieces"]),
        "due_in": (date.fromisoformat(row["due_date"]) - TODAY).days,
    }


def _is_eligible(workshop, job):
    return (
        workshop.status == "ACTIVE"
        and job["category"] in workshop.makes
        and (workshop.max_batch is None or job["pieces"] <= workshop.max_batch)
    )


def _finish_times(workshop, jobs):
    """Return job completion offsets, including initial availability and pickup lead."""
    work_done = workshop.available_day
    finish_times = []
    for job in jobs:
        work_done += job["pieces"] / workshop.capacity
        finish_times.append(work_done + workshop.lead_days)
    return finish_times


def insert_order(order_id, workshops):
    """Insert an order into `workshops` if it and queued orders can meet their due dates.

    `workshops` is the dictionary returned by `load_workshops()`. Successful assignments
    are stored on the selected workshop and remain in its queue for subsequent calls.
    Returns the assignment details on success, or None if no insertion is feasible.
    Raises ValueError for an unknown order or an order already assigned to a queue.
    """
    _initialize_workshops(workshops)
    orders = _load_orders()
    if order_id not in orders:
        raise ValueError(f"unknown order {order_id}")

    if any(job["order_id"] == order_id
           for workshop in workshops.values()
           for job in workshop.production_queue):
        raise ValueError(f"order {order_id} is already assigned to a workshop")

    new_job = _job(orders[order_id])
    best = None
    for workshop in workshops.values():
        if not _is_eligible(workshop, new_job):
            continue

        jobs = workshop.production_queue
        existing_finishes = _finish_times(workshop, jobs)
        on_time_orders = {
            job["order_id"]
            for job, finish in zip(jobs, existing_finishes)
            if finish <= job["due_in"]
        }
        for position in range(len(jobs) + 1):
            trial = jobs[:position] + [new_job] + jobs[position:]
            finishes = _finish_times(workshop, trial)
            remains_on_time = all(
                finish <= job["due_in"]
                for job, finish in zip(trial, finishes)
                if job["order_id"] == order_id or job["order_id"] in on_time_orders
            )
            if not remains_on_time:
                continue
            if best is None or finishes[position] < best["finish_day"]:
                best = {
                    "workshop": workshop,
                    "position": position,
                    "finish_day": finishes[position],
                    "queue": trial,
                    "finishes": finishes,
                }

    if best is None:
        return None

    workshop = best["workshop"]
    workshop.production_queue = best["queue"]
    result = {
        "order_id": order_id,
        "workshop_id": workshop.workshop_id,
        "position": best["position"],
        "finish_day": round(best["finish_day"], 2),
        "queue": [
            (job["order_id"], round(finish, 2), job["due_in"])
            for job, finish in zip(best["queue"], best["finishes"])
        ],
    }
    return result


if __name__ == "__main__":
    workshops = load_workshops()
    first = insert_order("ORD-109", {"W6": workshops["W6"]})
    if first is None:
        raise RuntimeError("ORD-109 could not be assigned to W6")
    print(
        f"Initial assignment: ORD-109 -> W6 "
        f"(done day {first['finish_day']})"
    )

    inserted = insert_order("ORD-045", workshops)
    if inserted is None:
        print("ORD-045 cannot be inserted without making a queued order late")
    else:
        print(
            f"Inserted ORD-045 -> {inserted['workshop_id']} at position "
            f"{inserted['position']} (done day {inserted['finish_day']})"
        )

    print("Updated production queues:")
    for workshop_id, workshop in workshops.items():
        if not workshop.production_queue:
            continue
        finishes = _finish_times(workshop, workshop.production_queue)
        print(f"{workshop_id}:")
        for job, finish in zip(workshop.production_queue, finishes):
            print(
                f"  {job['order_id']}: finishes day {finish:.2f}, "
                f"due day {job['due_in']}"
            )
