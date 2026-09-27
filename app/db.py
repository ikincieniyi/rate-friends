import sqlite3
import os
import secrets
from contextlib import contextmanager

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS polls (
 id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 name TEXT NOT NULL,
 poll_token TEXT NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('manual','automatic')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 revealed INTEGER NOT NULL DEFAULT 0 CHECK(revealed IN (0,1))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_poll ON polls(active) WHERE active=1;
CREATE TABLE IF NOT EXISTS participants (
 id INTEGER PRIMARY KEY AUTOINCREMENT, poll_id INTEGER NOT NULL REFERENCES polls(id),
 name TEXT NOT NULL, code_hash TEXT NOT NULL,
 auth_tag TEXT NOT NULL,
 completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0,1)),
 UNIQUE(poll_id,name), UNIQUE(code_hash)
);
CREATE TABLE IF NOT EXISTS categories (
 id INTEGER PRIMARY KEY, poll_id INTEGER NOT NULL REFERENCES polls(id),
 name TEXT NOT NULL, position INTEGER NOT NULL,
 UNIQUE(poll_id,name), UNIQUE(poll_id,position)
);
CREATE TABLE IF NOT EXISTS totals (
 poll_id INTEGER NOT NULL REFERENCES polls(id),
 target_id INTEGER NOT NULL REFERENCES participants(id),
 category_id INTEGER NOT NULL REFERENCES categories(id),
 score_sum INTEGER NOT NULL DEFAULT 0 CHECK(score_sum >= 0),
 vote_count INTEGER NOT NULL DEFAULT 0 CHECK(vote_count >= 0),
 PRIMARY KEY(target_id,category_id)
);
"""


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA journal_mode=WAL")
    try:
        yield db
    finally:
        db.close()


def init(path):
    if os.name == "posix":
        os.umask(0o077)
    with connect(path) as db:
        db.executescript(SCHEMA)
        with transaction(db):
            poll_columns = {row["name"] for row in db.execute("PRAGMA table_info(polls)")}
            if "name" not in poll_columns:
                db.execute("ALTER TABLE polls ADD COLUMN name TEXT NOT NULL DEFAULT 'Oylama'")
                db.execute("UPDATE polls SET name='Oylama #' || id")
            if "poll_token" not in poll_columns:
                db.execute("ALTER TABLE polls ADD COLUMN poll_token TEXT NOT NULL DEFAULT ''")
            for row in db.execute("SELECT id FROM polls WHERE poll_token='' ").fetchall():
                db.execute("UPDATE polls SET poll_token=? WHERE id=?", (secrets.token_urlsafe(24), row["id"]))
            person_columns = {row["name"] for row in db.execute("PRAGMA table_info(participants)")}
            if "auth_tag" not in person_columns:
                db.execute("ALTER TABLE participants ADD COLUMN auth_tag TEXT NOT NULL DEFAULT ''")
            for row in db.execute("SELECT id FROM participants WHERE auth_tag='' ").fetchall():
                db.execute("UPDATE participants SET auth_tag=? WHERE id=?", (secrets.token_urlsafe(24), row["id"]))
    if os.name == "posix":
        path.chmod(0o600)


@contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise
