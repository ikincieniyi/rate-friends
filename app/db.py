import sqlite3
import os
from contextlib import contextmanager

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS polls (
 id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 mode TEXT NOT NULL CHECK(mode IN ('manual','automatic')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 revealed INTEGER NOT NULL DEFAULT 0 CHECK(revealed IN (0,1))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_poll ON polls(active) WHERE active=1;
CREATE TABLE IF NOT EXISTS participants (
 id INTEGER PRIMARY KEY, poll_id INTEGER NOT NULL REFERENCES polls(id),
 name TEXT NOT NULL, code_hash TEXT NOT NULL,
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
