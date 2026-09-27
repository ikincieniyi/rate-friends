#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
set -a
. ./.env
set +a
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
