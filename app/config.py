import os
from pathlib import Path


def settings():
    password = os.environ.get("ADMIN_PASSWORD", "")
    secret = os.environ.get("SESSION_SECRET", "")
    if len(password) < 16 or len(secret) < 32:
        raise RuntimeError("ADMIN_PASSWORD (16+ chars) and SESSION_SECRET (32+ chars) are required")
    data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        data_dir.chmod(0o700)
    return password, secret, data_dir / "votes.sqlite3", os.environ.get("COOKIE_SECURE") == "1"
