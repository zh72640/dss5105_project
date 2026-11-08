"""Explicit, backed-up reset of a stopped demo database; never runs at startup."""
import argparse
from contextlib import closing
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from app.db.database import Database
from app.db.import_data import load_seed


def reset_demo(db_path, *, server_stopped=False):
    if not server_stopped:
        raise ValueError('Stop the server, then pass --server-stopped. No database was changed.')
    path = Path(db_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError('Provide an existing demo database file.')
    # A private, adjacent directory keeps staging/replace on the same filesystem.
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = path.parent / 'backups' / (path.stem + '-' + stamp)
    folder.mkdir(parents=True, mode=0o700)
    backup = folder / 'before-reset.sqlite3'
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=1)) as source:
        source.execute('PRAGMA busy_timeout=1000')
        if source.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
            raise ValueError('Database is busy. Stop the server before resetting.')
        with closing(sqlite3.connect(backup)) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Backup integrity check failed. Original database retained.')
        accounts = source.execute('SELECT username,password_hash,created_at,role FROM desk_users').fetchall()
    os.chmod(backup, 0o600)
    staging = folder / 'fresh.sqlite3'
    with Database(staging, seed_data=load_seed(as_of=date(2026,4,1))) as fresh:
        with fresh.transaction() as connection:
            connection.executemany('INSERT OR REPLACE INTO desk_users(username,password_hash,created_at,role) VALUES (?,?,?,?)', accounts)
        if fresh.connection.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Fresh database integrity check failed. Original database retained.')
    if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm')):
        raise ValueError('SQLite sidecars are still active. Original database retained; backup available.')
    os.chmod(staging, 0o600)
    os.replace(staging, path)
    manifest = {'database':str(path), 'backup':str(backup), 'business_date':'2026-04-01',
                'accounts_preserved':len(accounts), 'sign_in_again':True}
    (folder/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description='Replace a stopped demo database with bundled sample data; preserve accounts and back up everything first.')
    parser.add_argument('--db', required=True, type=Path, help='Explicit existing demo database path; no default target')
    parser.add_argument('--server-stopped', action='store_true', help='Confirm you have stopped every process using this database')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(reset_demo(args.db, server_stopped=args.server_stopped), indent=2))
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
