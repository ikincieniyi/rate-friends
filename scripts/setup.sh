#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt
if [ ! -e .env ]; then
  umask 077
  .venv/bin/python - <<'PY'
import getpass
import secrets
import shlex
from pathlib import Path

password = getpass.getpass('Yönetici parolası (en az 16 karakter): ')
if len(password) < 16 or '\n' in password or '\r' in password:
    raise SystemExit('Parola geçersiz veya çok kısa.')
secret = secrets.token_urlsafe(48)
Path('.env').write_text(
    f'ADMIN_PASSWORD={shlex.quote(password)}\n'
    f'SESSION_SECRET={shlex.quote(secret)}\n'
    'DATA_DIR=./data\nCOOKIE_SECURE=0\n', encoding='utf-8')
PY
  echo '.env oluşturuldu (yalnızca sahibi okuyabilir).'
else
  echo '.env zaten var; değiştirilmedi.'
fi
mkdir -p data
chmod 700 data
