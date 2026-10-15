"""Create regular accounts or explicitly reset their passwords."""
import argparse
import sqlite3
from pathlib import Path
from app.core.security import create_account, prompt_password, require_initialized, reset_password


def main():
    parser = argparse.ArgumentParser(description="Create a local account; password reset requires --reset-password.")
    parser.add_argument("username")
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[2] / "runtime/dispatch.sqlite3"))
    parser.add_argument("--reset-password", action="store_true", help="Reset an existing account and revoke its logins")
    args = parser.parse_args()
    try:
        require_initialized(args.db)
        password = prompt_password()
        (reset_password if args.reset_password else create_account)(args.db, args.username, password)
    except (ValueError, OSError, sqlite3.Error, EOFError) as error:
        parser.error(str(error))
    print("Password reset successfully. Existing logins have been revoked." if args.reset_password
          else "Account created successfully.")


if __name__ == "__main__":
    main()
