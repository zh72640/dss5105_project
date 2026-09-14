import csv
from pathlib import Path
from .models import Order, Workshop

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def load_orders() -> dict[str, Order]:
    with (DATA_DIR / "orders.csv").open(encoding="utf-8") as handle:
        return {r["order_id"]: Order(r["order_id"], r["customer"], r["product"], r["category"],
            int(r["pieces"]), r["due_date"]) for r in csv.DictReader(handle)}


def load_workshops() -> dict[str, Workshop]:
    with (DATA_DIR / "workshops.csv").open(encoding="utf-8") as handle:
        return {r["workshop_id"]: Workshop(r["workshop_id"], r["name"],
            int(r["capacity_pieces_per_day"]), int(r["pickup_lead_days"]), float(r["defect_rate"]),
            float(r["cost_per_piece"]), frozenset(r["makes"].split("+")), r["status"],
            int(r["max_batch_pieces"]) if r["max_batch_pieces"] else None,
            float(r["current_queue_days"]), r["notes"]) for r in csv.DictReader(handle)}

