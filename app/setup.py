"""Explicit first-run CSV import and account creation. Never replaces a database."""
import argparse
import sqlite3
from datetime import date
from pathlib import Path
from app.auth import password_hash, prompt_password, validate_credentials
from app.db.database import Database
from app.db.import_data import ROOT, load_seed


def initialize_database(db_path, seed, username, password):
    validate_credentials(username, password)
    account = (username, password_hash(password))
    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects an empty file and concurrent setup processes.
    try:
        with path.open("xb"):
            pass
    except FileExistsError as error:
        raise ValueError("Database already exists; choose a new --db path. Existing data was not changed.") from error
    try:
        with Database(path, seed_data=seed, initial_account=account):
            pass
    except BaseException:
        # Only remove the new file this invocation exclusively created, after DB close.
        path.unlink()
        raise
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Initialize a NEW database from sample or personal CSV files and create its first account.")
    parser.add_argument("--db", type=Path, default=ROOT / "runtime/dispatch.sqlite3")
    parser.add_argument("--sample", action="store_true", help="Use the two CSV files in data/")
    parser.add_argument("--orders", type=Path, help="Personal orders CSV (requires --workshops)")
    parser.add_argument("--workshops", type=Path, help="Personal workshops CSV (requires --orders)")
    parser.add_argument("--as-of", type=date.fromisoformat, help="Queue snapshot date: YYYY-MM-DD")
    parser.add_argument("--username", help="First account name; prompted when omitted")
    parser.add_argument("--yes", action="store_true", help="Confirm the displayed import; password is still prompted securely")
    args = parser.parse_args(argv)
    if args.sample and (args.orders or args.workshops):
        parser.error("Choose --sample OR both --orders and --workshops.")
    if bool(args.orders) != bool(args.workshops):
        parser.error("Provide both --orders and --workshops.")
    try:
        if args.db.exists():
            raise ValueError("Database already exists; choose a new --db path. To use an existing database, start app.server.")
        sample = args.sample
        if not sample and args.orders is None:
            choice = input("Data source: [1] bundled sample (default), [2] personal CSV: ").strip() or "1"
            if choice not in {"1", "2"}:
                raise ValueError("Choose 1 or 2.")
            sample = choice == "1"
            if not sample:
                args.orders = Path(input("Orders CSV path: ").strip().strip('"'))
                args.workshops = Path(input("Workshops CSV path: ").strip().strip('"'))
        default_date = date(2026, 4, 1) if sample else date.today()
        as_of = args.as_of
        if as_of is None:
            value = input(f"Queue snapshot / business date [{default_date.isoformat()}]: ").strip()
            as_of = date.fromisoformat(value) if value else default_date
        seed = load_seed(ROOT / "data/orders.csv" if sample else args.orders,
                         ROOT / "data/workshops.csv" if sample else args.workshops, as_of)
        completed = sum(row["status"] == "COMPLETE" for row in seed.orders)
        print(f"Import: {len(seed.orders)} orders ({completed} completed), {len(seed.workshops)} workshops.")
        print(f"Business date: {as_of.isoformat()} | New database: {args.db.resolve()}")
        if any(row["status"] == "IN_PROGRESS" for row in seed.orders):
            print("IN_PROGRESS source orders will become READY; existing production assignments are not imported.")
        if not args.yes and input("Create this database? [y/N]: ").strip().lower() not in {"y", "yes"}:
            print("Cancelled. No database was created.")
            return 0
        username = args.username or input("First account username: ").strip()
        path = initialize_database(args.db, seed, username, prompt_password())
        print("Database initialized successfully. Account created successfully.")
        print(f'Next (offline): uv run --locked python -m app.server --db "{path}" --backend offline')
        print(f'Next (Gemini):  uv run --locked --env-file .env python -m app.server --db "{path}" --backend llm')
        print("Copy .env.example to .env and set GEMINI_API_KEY first. The app does not auto-load .env;")
        print("deployments should inject keys into the process environment instead.")
        print("Open http://127.0.0.1:8000 and sign in.")
        return 0
    except (ValueError, OSError, sqlite3.Error, EOFError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
