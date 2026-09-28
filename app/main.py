import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import rules
from .auth import check_csrf, csrf_token, limited, require_admin, voter_id
from .config import settings
from .db import connect, init
from .results_view import result_cards

ADMIN_PASSWORD, SESSION_SECRET, DB_PATH, COOKIE_SECURE = settings()


@asynccontextmanager
async def lifespan(app):
    init(DB_PATH)
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, https_only=COOKIE_SECURE, same_site="lax", session_cookie="rate_friends_session", max_age=86400)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def page(request, template, status_code=200, **context):
    return templates.TemplateResponse(request, template, {"csrf": csrf_token(request), "admin": bool(request.session.get("admin")), **context}, status_code=status_code, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def redirect(path):
    return RedirectResponse(path, status_code=303, headers={"Cache-Control": "no-store"})


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with connect(DB_PATH) as db:
        poll = rules.active_poll(db)
        if not poll:
            return page(request, "home.html", poll=None)
        done, count = rules.progress(db, poll["id"])
        people = db.execute("SELECT id,name FROM participants WHERE poll_id=? ORDER BY id", (poll["id"],)).fetchall()
        return page(request, "home.html", poll=poll, done=done, count=count, people=people)


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    check_csrf(request, form)
    with connect(DB_PATH) as db:
        poll = rules.active_poll(db)
        if not poll:
            return page(request, "home.html", poll=None, error="Aktif oylama yok.", status_code=400)
        try:
            person_id = int(form.get("person", ""))
        except (ValueError, TypeError):
            person_id = -1
        if limited(request, "voter", str(person_id)):
            raise HTTPException(429, "Çok fazla deneme. 15 dakika sonra tekrar deneyin.")
        code = form.get("code", "")
        person = rules.authenticate_participant(db, poll["id"], person_id, code if isinstance(code, str) else "")
        if not person:
            done, count = rules.progress(db, poll["id"])
            people = db.execute("SELECT id,name FROM participants WHERE poll_id=? ORDER BY id", (poll["id"],)).fetchall()
            return page(request, "home.html", poll=poll, done=done, count=count, people=people, error="Ad veya kod hatalı.", status_code=400)
    request.session["voter_id"] = person_id
    request.session["poll_id"] = poll["id"]
    request.session["auth_tag"] = person["auth_tag"]
    return redirect("/vote")


@app.get("/vote", response_class=HTMLResponse)
def vote(request: Request):
    with connect(DB_PATH) as db:
        poll = rules.active_poll(db)
        if not poll:
            raise HTTPException(404)
        who = voter_id(request, poll["id"], db)
        person = db.execute("SELECT name,completed FROM participants WHERE id=? AND poll_id=?", (who, poll["id"])).fetchone()
        if not person:
            raise HTTPException(403)
        if person["completed"]:
            return redirect("/results" if poll["revealed"] else "/")
        people, categories = rules.ballot(db, poll["id"], who)
        return page(request, "vote.html", person=person, people=people, categories=categories)


@app.post("/preview", response_class=HTMLResponse)
async def preview(request: Request):
    form = await request.form(max_fields=6005)
    check_csrf(request, form)
    with connect(DB_PATH) as db:
        poll = rules.active_poll(db)
        if not poll:
            raise HTTPException(404)
        who = voter_id(request, poll["id"], db)
        person = db.execute("SELECT completed FROM participants WHERE id=?", (who,)).fetchone()
        if not person or person["completed"]:
            raise HTTPException(409, "Oy zaten gönderilmiş.")
        people, categories = rules.ballot(db, poll["id"], who)
        try:
            scores = rules.validate_scores(db, poll["id"], who, form)
        except rules.InvalidVote as exc:
            return page(request, "vote.html", people=people, categories=categories, error=str(exc), values=form, status_code=400)
        return page(request, "preview.html", people=people, categories=categories, scores=scores)


@app.post("/submit")
async def submit(request: Request):
    form = await request.form(max_fields=6005)
    check_csrf(request, form)
    with connect(DB_PATH) as db:
        poll = rules.active_poll(db)
        if not poll:
            raise HTTPException(404)
        who = voter_id(request, poll["id"], db)
        try:
            scores = rules.validate_scores(db, poll["id"], who, form)
        except rules.InvalidVote as exc:
            raise HTTPException(400, str(exc))
        try:
            rules.submit_vote(db, poll["id"], who, scores, request.session["auth_tag"])
        except rules.InvalidVote as exc:
            raise HTTPException(409, str(exc))
    return redirect("/results" if poll["mode"] == "automatic" else "/")


@app.get("/results", response_class=HTMLResponse)
def results(request: Request):
    with connect(DB_PATH) as db:
        poll = rules.active_poll(db)
        if not poll:
            raise HTTPException(404)
        if not request.session.get("admin"):
            voter_id(request, poll["id"], db)
        if not poll["revealed"]:
            return redirect("/")
        rows, expected = rules.results(db, poll["id"])
        return page(request, "results.html", cards=result_cards(rows), expected=expected)


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login(request: Request):
    return page(request, "admin_login.html")


@app.post("/admin/login")
async def admin_login_post(request: Request):
    form = await request.form()
    check_csrf(request, form)
    if limited(request, "admin", "admin"):
        raise HTTPException(429, "Çok fazla deneme. 15 dakika sonra tekrar deneyin.")
    password = form.get("password", "")
    if not isinstance(password, str) or not secrets.compare_digest(password, ADMIN_PASSWORD):
        return page(request, "admin_login.html", error="Parola hatalı.", status_code=400)
    request.session.clear()
    request.session["admin"] = True
    return redirect("/admin")


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    require_admin(request)
    with connect(DB_PATH) as db:
        poll = rules.active_poll(db)
        if poll:
            done, count = rules.progress(db, poll["id"])
            people = db.execute("SELECT id,name FROM participants WHERE poll_id=? ORDER BY id", (poll["id"],)).fetchall()
            return page(request, "admin.html", poll=poll, done=done, count=count, people=people, defaults=rules.DEFAULT_CATEGORIES)
        return page(request, "admin.html", poll=None, defaults=rules.DEFAULT_CATEGORIES)


@app.post("/admin/create", response_class=HTMLResponse)
async def admin_create(request: Request):
    require_admin(request)
    form = await request.form()
    check_csrf(request, form)
    names = form.get("names", "")
    categories = form.get("categories", "")
    mode = form.get("mode", "")
    name = form.get("name", "")
    with connect(DB_PATH) as db:
        try:
            _, codes = rules.create_poll(db, names, categories, mode, name)
        except (ValueError, TypeError) as exc:
            poll = rules.active_poll(db)
            done, count = rules.progress(db, poll["id"]) if poll else (0, 0)
            people = db.execute("SELECT id,name FROM participants WHERE poll_id=? ORDER BY id", (poll["id"],)).fetchall() if poll else []
            return page(request, "admin.html", poll=poll, done=done, count=count, people=people, defaults=categories, names=names, poll_name=name, error=str(exc), status_code=400)
    return page(request, "codes.html", codes=codes)


@app.get("/admin/delete", response_class=HTMLResponse)
def admin_delete_confirm(request: Request):
    require_admin(request)
    with connect(DB_PATH) as db:
        poll = rules.active_poll(db)
        if not poll:
            raise HTTPException(404)
        return page(request, "delete_confirm.html", poll=poll)


@app.post("/admin/delete")
async def admin_delete(request: Request):
    require_admin(request)
    form = await request.form()
    check_csrf(request, form)
    try:
        poll_id = int(form.get("poll_id", ""))
    except (TypeError, ValueError):
        raise HTTPException(400, "Oylama onayı geçersiz.")
    with connect(DB_PATH) as db:
        try:
            rules.delete_poll(db, poll_id, form.get("confirm_name", ""), form.get("poll_token", ""))
        except ValueError as exc:
            raise HTTPException(409, str(exc))
    for key in ("voter_id", "poll_id", "auth_tag"):
        request.session.pop(key, None)
    return redirect("/admin")


@app.post("/admin/rotate/{person_id}", response_class=HTMLResponse)
async def admin_rotate(request: Request, person_id: int):
    require_admin(request)
    form = await request.form()
    check_csrf(request, form)
    try:
        poll_id = int(form.get("poll_id", ""))
    except (TypeError, ValueError):
        raise HTTPException(400, "Oylama değişti.")
    with connect(DB_PATH) as db:
        try:
            name, code = rules.rotate_code(db, poll_id, person_id, form.get("poll_token", ""))
        except ValueError as exc:
            raise HTTPException(409, str(exc))
    return page(request, "new_code.html", name=name, code=code)


@app.post("/admin/reveal")
async def admin_reveal(request: Request):
    require_admin(request)
    form = await request.form()
    check_csrf(request, form)
    with connect(DB_PATH) as db:
        poll = rules.active_poll(db)
        if not poll:
            raise HTTPException(404)
        try:
            rules.reveal(db, poll["id"])
        except ValueError as exc:
            raise HTTPException(409, str(exc))
    return redirect("/results")


@app.post("/logout")
async def logout(request: Request):
    form = await request.form()
    check_csrf(request, form)
    request.session.clear()
    return redirect("/")
