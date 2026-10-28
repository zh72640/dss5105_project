"""Account identity helpers for HTTP and callers."""
from app.core import security as auth_mod
from app.db import account_repository
from app.db.database import Database


def identify_principal(db_path, token):
    return auth_mod.identify_principal(db_path, token)


def login(db_path, username, password):
    return auth_mod.login(db_path, username, password)


def logout(db_path, token):
    return auth_mod.logout(db_path, token)


def auth_me(db_path, username, *, require_auth):
    with Database(db_path) as db:
        setup = account_repository.count_non_admin_users(db.connection) == 0
        role_row = account_repository.role_for_username(db.connection, username)
    role = role_row if require_auth and role_row else ("user" if not require_auth and username else None)
    return {"username": username, "role": role, "auth_required": require_auth,
            "setup_required": require_auth and setup}
