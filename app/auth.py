"""Local desk accounts and revocable eight-hour browser sessions.

Create/reset a local account with python -m app.auth USERNAME --db PATH.
Passwords are prompted without echo and never accepted as CLI arguments.
"""
import argparse
import getpass
import hashlib
import hmac
import re
import secrets
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


def set_password(db_path, username, password):
    if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username):
        raise ValueError("Use 1–64 letters, numbers, dots, underscores or hyphens for the username.")
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("Use a password between 12 and 256 characters.")
    encoded = password_hash(password)
    with Database(db_path) as db, db.transaction() as connection:
        connection.execute("""INSERT INTO desk_users VALUES (?,?,?)
            ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash""",
            (username, encoded, utc_now()))
        connection.execute("DELETE FROM login_sessions WHERE username=?", (username,))


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
    parser = argparse.ArgumentParser(description="Create a local account or reset its password and revoke its logins.")
    parser.add_argument("username")
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "runtime/dispatch.sqlite3"))
    args = parser.parse_args()
    password = getpass.getpass("Password (12–256 characters): ")
    if password != getpass.getpass("Repeat password: "):
        parser.error("Passwords do not match.")
    try:
        set_password(args.db, args.username, password)
    except ValueError as error:
        parser.error(str(error))
    print(f"Account {args.username} is ready. Existing logins for this account have been revoked.")


if __name__ == "__main__":
    main()
