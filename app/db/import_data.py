"""Validated CSV snapshots for first-time database creation; no database writes."""
import csv
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORDER_FIELDS = ("order_id", "customer", "product", "category", "pieces", "order_date", "due_date", "status")
WORKSHOP_FIELDS = ("workshop_id", "name", "capacity_pieces_per_day", "pickup_lead_days",
                   "defect_rate", "cost_per_piece", "makes", "status", "current_queue_days")
CATEGORIES = {"TOPS", "ACCESSORIES"}


@dataclass
class SeedData:
    orders: list[dict]
    workshops: list[dict]
    as_of: date


def _rows(path, required):
    path = Path(path)
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            fields = reader.fieldnames or []
            if len(fields) != len(set(fields)):
                raise ValueError(f"{path}: duplicate column names")
            missing = set(required) - set(fields)
            if missing:
                raise ValueError(f"{path}: missing columns: {', '.join(sorted(missing))}")
            for row in reader:
                line = reader.line_num
                if None in row or any(v is None for v in row.values()):
                    raise ValueError(f"{path}: row {line}: column count does not match the header")
                yield line, {k: v.strip() for k, v in row.items()}
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValueError(f"{path}: cannot read UTF-8 CSV: {error}") from error


def _integer(row, key, minimum):
    value = int(row[key])
    if value < minimum or value > 2**31 - 1:
        raise ValueError(f"{key} must be an integer between {minimum} and {2**31 - 1}")
    row[key] = value


def _number(row, key, maximum=None):
    value = float(row[key])
    if not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        raise ValueError(f"{key} must be finite and >= 0" + (f" and <= {maximum}" if maximum is not None else ""))
    row[key] = value


def _date(value, key):
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError(f"{key} must use YYYY-MM-DD")
    return value


def load_seed(orders_path=ROOT / "data/orders.csv", workshops_path=ROOT / "data/workshops.csv",
              as_of=date(2026, 4, 1)):
    if type(as_of) is not date:
        raise ValueError("Business date must be a date")
    orders, workshops = [], []
    for path, fields, target, kind in ((orders_path, ORDER_FIELDS, orders, "order"),
                                      (workshops_path, WORKSHOP_FIELDS, workshops, "workshop")):
        seen, names = set(), set()
        for line, row in _rows(path, fields):
            try:
                for key in fields:
                    if not row[key]:
                        raise ValueError(f"{key} is required")
                id_key = kind + "_id"
                pattern = r"ORD-\d{3}|O\d+" if kind == "order" else r"W[1-9]\d*"
                if not re.fullmatch(pattern, row[id_key]):
                    raise ValueError(f"{id_key} must match {pattern}")
                if row[id_key] in seen:
                    raise ValueError(f"duplicate {id_key}: {row[id_key]}")
                seen.add(row[id_key])
                if kind == "order":
                    if row["category"] not in CATEGORIES:
                        raise ValueError("category must be TOPS or ACCESSORIES")
                    _integer(row, "pieces", 1)
                    for key in ("order_date", "due_date"):
                        _date(row[key], key)
                    if row["due_date"] < row["order_date"]:
                        raise ValueError("due_date precedes order_date")
                    if row["status"] not in {"READY", "IN_PROGRESS", "COMPLETE"}:
                        raise ValueError("status must be READY, IN_PROGRESS or COMPLETE")
                    row["completed_date"] = row.get("completed_date", "")
                    if row["completed_date"]:
                        _date(row["completed_date"], "completed_date")
                        if row["status"] != "COMPLETE" or row["completed_date"] < row["order_date"]:
                            raise ValueError("completed_date requires COMPLETE and cannot precede order_date")
                else:
                    if row["name"] in names:
                        raise ValueError(f"duplicate workshop name: {row['name']}")
                    names.add(row["name"])
                    _integer(row, "capacity_pieces_per_day", 1)
                    _integer(row, "pickup_lead_days", 0)
                    _number(row, "defect_rate", 1)
                    _number(row, "cost_per_piece")
                    _number(row, "current_queue_days")
                    if not set(row["makes"].split("+")) <= CATEGORIES:
                        raise ValueError("makes must be TOPS, ACCESSORIES or TOPS+ACCESSORIES")
                    if row["status"] not in {"ACTIVE", "SUSPENDED", "INACTIVE"}:
                        raise ValueError("status must be ACTIVE, SUSPENDED or INACTIVE")
                    row["max_batch_pieces"] = row.get("max_batch_pieces", "")
                    if row["max_batch_pieces"]:
                        _integer(row, "max_batch_pieces", 1)
                    else:
                        row["max_batch_pieces"] = None
                    row["notes"] = row.get("notes", "")
                target.append(row)
            except (ValueError, OverflowError) as error:
                raise ValueError(f"{path}: row {line}: {error}") from error
        if not target:
            raise ValueError(f"{path}: at least one {kind} is required")
    if len(workshops) > 8:
        raise ValueError(f"{workshops_path}: this planner supports at most 8 workshops; found {len(workshops)}")
    return SeedData(orders, workshops, as_of)
