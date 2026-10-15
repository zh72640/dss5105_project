"""Local desk accounts and revocable eight-hour browser sessions.

Create with python -m app.cli.auth USERNAME; explicitly reset with --reset-password.
Passwords are prompted without echo and never accepted as CLI arguments.
"""
import getpass
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from pathlib import Path

from app.db.database import Database, utc_now
from app.core.admin_account import ensure_regular_username

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


def validate_regular_credentials(username, password):
    validate_credentials(username, password)
    ensure_regular_username(username)


def _require_regular_account(connection, username):
    row = connection.execute("SELECT role FROM desk_users WHERE username=?", (username,)).fetchone()
    if row and row["role"] != "user":
        raise ValueError("Administrator accounts cannot be changed through ordinary account commands.")


def set_password(db_path, username, password):
    """Legacy internal create/reset helper used by isolated demos and tests."""
    validate_regular_credentials(username, password)
    encoded = password_hash(password)
    with Database(db_path) as db, db.transaction() as connection:
        _require_regular_account(connection, username)
        connection.execute("""INSERT INTO desk_users (username,password_hash,created_at,role) VALUES (?,?,?,'user')
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
                raise ValueError("Database is not initialized. Run uv run python -m app.cli.setup first.")
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise ValueError("Cannot open initialized database. Run uv run python -m app.cli.setup first, and check --db.") from error


def create_account(db_path, username, password):
    require_initialized(db_path)
    validate_regular_credentials(username, password)
    encoded = password_hash(password)
    with Database(db_path) as db, db.transaction() as connection:
        if connection.execute("SELECT 1 FROM desk_users WHERE username=?", (username,)).fetchone():
            raise ValueError("Account already exists. Please sign in or use --reset-password.")
        connection.execute("INSERT INTO desk_users (username,password_hash,created_at,role) VALUES (?,?,?,'user')",
                           (username, encoded, utc_now()))


def reset_password(db_path, username, password):
    require_initialized(db_path)
    validate_regular_credentials(username, password)
    encoded = password_hash(password)
    with Database(db_path) as db, db.transaction() as connection:
        _require_regular_account(connection, username)
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


def identify_principal(db_path, token):
    if not token or len(token) > 128:
        return None
    with Database(db_path) as db:
        row = db.connection.execute("""SELECT u.username,u.role FROM login_sessions s
            JOIN desk_users u ON u.username=s.username WHERE s.token_hash=? AND s.expires_at>?""",
            (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return dict(row) if row else None


def identify(db_path, token):
    """Historical username-only interface for scripts and business callers."""
    principal = identify_principal(db_path, token)
    return principal["username"] if principal else None


def logout(db_path, token):
    with Database(db_path) as db:
        db.connection.execute("DELETE FROM login_sessions WHERE token_hash=?",
                              (hashlib.sha256(token.encode()).hexdigest(),))
