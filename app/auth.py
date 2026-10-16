"""Local desk accounts and revocable eight-hour browser sessions.

Create with python -m app.auth USERNAME; explicitly reset with --reset-password.
Passwords are prompted without echo and never accepted as CLI arguments.
"""
import argparse
import getpass
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from pathlib import Path

from app.db.database import Database, utc_now

COOKIE = "sweaterco_login"
TTL = 8 * 60 * 60
ITERATIONS = 600_000


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return f"{salt}${digest}"


def validate_credentials(username, password):
    if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username):
        raise ValueError("Use 1–64 letters, numbers, dots, underscores or hyphens for the username.")
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("Use a password between 12 and 256 characters.")


def set_password(db_path, username, password):
    """Legacy internal create/reset helper used by isolated demos and tests."""
    validate_credentials(username, password)
    encoded = password_hash(password)
    with Database(db_path) as db, db.transaction() as connection:
        connection.execute("""INSERT INTO desk_users VALUES (?,?,?)
            ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash""",
            (username, encoded, utc_now()))
        connection.execute("DELETE FROM login_sessions WHERE username=?", (username,))


def require_initialized(db_path):
    """Read-only preflight: account/server CLI must not silently seed demo data."""
    path = Path(db_path).resolve()
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            if not connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]:
                raise ValueError("Database is not initialized. Run uv run python -m app.setup first.")
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise ValueError("Cannot open initialized database. Run uv run python -m app.setup first, and check --db.") from error


def create_account(db_path, username, password):
    require_initialized(db_path)
    validate_credentials(username, password)
    encoded = password_hash(password)
    with Database(db_path) as db, db.transaction() as connection:
        if connection.execute("SELECT 1 FROM desk_users WHERE username=?", (username,)).fetchone():
            raise ValueError("Account already exists. Please sign in or use --reset-password.")
        connection.execute("INSERT INTO desk_users VALUES (?,?,?)", (username, encoded, utc_now()))


def reset_password(db_path, username, password):
    require_initialized(db_path)
    validate_credentials(username, password)
    encoded = password_hash(password)
    with Database(db_path) as db, db.transaction() as connection:
        changed = connection.execute("UPDATE desk_users SET password_hash=? WHERE username=?", (encoded, username))
        if changed.rowcount != 1:
            raise ValueError("Account does not exist. Create it without --reset-password.")
        connection.execute("DELETE FROM login_sessions WHERE username=?", (username,))


def prompt_password():
    password = getpass.getpass("Password (12–256 characters): ")
    if password != getpass.getpass("Repeat password: "):
        raise ValueError("Passwords do not match.")
    return password


def login(db_path, username, password):
    if not isinstance(username, str) or not isinstance(password, str) or len(username) > 64 or len(password) > 256:
        return None
    with Database(db_path) as db:
        user = db.connection.execute("SELECT password_hash FROM desk_users WHERE username=?", (username,)).fetchone()
        # Perform the same expensive hash for unknown usernames.
        encoded = user[0] if user else "0" * 32 + "$" + "0" * 64
        valid = hmac.compare_digest(password_hash(password, encoded.split("$")[0]), encoded)
        if not user or not valid:
            return None
        token = secrets.token_urlsafe(32)
        with db.transaction() as connection:
            # A concurrent password reset must invalidate this in-flight login too.
            latest = connection.execute("SELECT password_hash FROM desk_users WHERE username=?", (username,)).fetchone()
            if not latest or latest[0] != encoded:
                return None
            connection.execute("DELETE FROM login_sessions WHERE expires_at<=?", (time.time(),))
            connection.execute("INSERT INTO login_sessions VALUES (?,?,?)",
                               (hashlib.sha256(token.encode()).hexdigest(), username, time.time() + TTL))
        return token


def identify(db_path, token):
    if not token or len(token) > 128:
        return None
    with Database(db_path) as db:
        row = db.connection.execute("SELECT username FROM login_sessions WHERE token_hash=? AND expires_at>?",
            (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return row[0] if row else None


def logout(db_path, token):
    with Database(db_path) as db:
        db.connection.execute("DELETE FROM login_sessions WHERE token_hash=?",
                              (hashlib.sha256(token.encode()).hexdigest(),))


def main():
    parser = argparse.ArgumentParser(description="Create a local account; password reset requires --reset-password.")
    parser.add_argument("username")
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "runtime/dispatch.sqlite3"))
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
