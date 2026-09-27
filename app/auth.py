import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_attempts = defaultdict(deque)


def limited(request: Request, kind: str, identity: str) -> bool:
    # One worker is used in production. Bound the map and old entries.
    now = time.monotonic()
    if len(_attempts) > 10000:
        _attempts.clear()
    key = (kind, request.client.host if request.client else "unknown", identity)
    attempts = _attempts[key]
    while attempts and now - attempts[0] > 900:
        attempts.popleft()
    if len(attempts) >= 8:
        return True
    attempts.append(now)
    return False


def csrf_token(request: Request):
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def check_csrf(request: Request, form):
    known = request.session.get("csrf", "")
    supplied = form.get("csrf", "")
    if not known or not isinstance(supplied, str) or not secrets.compare_digest(known, supplied):
        raise HTTPException(403, "Geçersiz form anahtarı. Sayfayı yenileyin.")


def require_admin(request: Request):
    if not request.session.get("admin"):
        raise HTTPException(403, "Yönetici girişi gerekli.")


def voter_id(request: Request, poll_id):
    if request.session.get("poll_id") != poll_id or not isinstance(request.session.get("voter_id"), int):
        raise HTTPException(403, "Katılımcı girişi gerekli.")
    return request.session["voter_id"]
