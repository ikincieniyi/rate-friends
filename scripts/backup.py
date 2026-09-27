"""SQLite online backup; destination should be outside the repository."""
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("Usage: python scripts/backup.py /secure/backup/directory")
source = Path(os.environ.get("DATA_DIR", "./data")) / "votes.sqlite3"
if not source.is_file():
    raise SystemExit("Database not found")
destination_dir = Path(sys.argv[1]).resolve()
destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
destination = destination_dir / f"votes-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.sqlite3"
with sqlite3.connect(source) as input_db, sqlite3.connect(destination) as output_db:
    input_db.backup(output_db)
destination.chmod(0o600)
print(destination)
