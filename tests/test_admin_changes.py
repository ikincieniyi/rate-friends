import os
import re
import sqlite3

os.environ.setdefault("ADMIN_PASSWORD", "test-password-long-enough")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-long-enough-for-tests")
os.environ.setdefault("DATA_DIR", "./data-test")

import pytest
from fastapi.testclient import TestClient

from app import rules
from app.db import connect, init
from app.main import app


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "votes.sqlite3"
    init(path)
    monkeypatch.setattr("app.main.DB_PATH", path)
    return path


def create(path, name="Arkadaş Grubu"):
    with connect(path) as db:
        poll_id, codes = rules.create_poll(db, "Ada\nBora\nCem", "Style\nAnnoying", "manual", name)
        people = db.execute("SELECT id,name FROM participants WHERE poll_id=? ORDER BY id", (poll_id,)).fetchall()
        token = rules.active_poll(db)["poll_token"]
    return poll_id, token, codes, people


def csrf(html):
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def admin_login(client):
    token = csrf(client.get("/admin/login").text)
    response = client.post("/admin/login", data={"csrf": token, "password": "test-password-long-enough"}, follow_redirects=False)
    assert response.status_code == 303
    return csrf(client.get("/admin").text)


def voter_login(client, person_id, code):
    token = csrf(client.get("/").text)
    response = client.post("/login", data={"csrf": token, "person": person_id, "code": code}, follow_redirects=False)
    assert response.status_code == 303
    return token


def scores(path, poll_id, voter_id):
    with connect(path) as db:
        people, categories = rules.ballot(db, poll_id, voter_id)
    return {f"score_{p['id']}_{c['id']}": "7" for p in people for c in categories}


def test_radio_ballot_and_required_scores(db_path):
    poll_id, _, codes, people = create(db_path)
    with TestClient(app) as client:
        token = voter_login(client, people[0]["id"], codes[0][1])
        html = client.get("/vote").text
        for key in scores(db_path, poll_id, people[0]["id"]):
            choices = re.findall(rf'type="radio" name="{key}" value="(\d+)" required', html)
            assert choices == [str(i) for i in range(1, 11)]
        assert '<select' not in html
        ballot = scores(db_path, poll_id, people[0]["id"])
        missing = dict(ballot)
        missing.pop(next(iter(missing)))
        response = client.post("/preview", data={"csrf": token, **missing})
        assert response.status_code == 400
        assert 'value="7" required checked' in response.text
        assert client.post("/preview", data={"csrf": token, **ballot}).status_code == 200


def test_delete_only_selected_poll_and_reject_stale_sessions(db_path):
    old_id, _, _, old_people = create(db_path, "Eski oylama")
    with connect(db_path) as db:
        for person in old_people:
            ballot = {(int(k.split("_")[1]), int(k.split("_")[2])): int(v) for k, v in scores(db_path, old_id, person["id"]).items()}
            rules.submit_vote(db, old_id, person["id"], ballot)
        rules.reveal(db, old_id)
    poll_id, token, codes, people = create(db_path, "Silinecek oylama")
    with TestClient(app) as voter, TestClient(app) as admin:
        assert voter.get("/admin/delete").status_code == 403
        voter_login(voter, people[0]["id"], codes[0][1])
        admin_csrf = admin_login(admin)
        confirmation = admin.get("/admin/delete")
        assert "Silinecek oylama" in confirmation.text
        assert "geri alınamaz" in confirmation.text
        bad = admin.post("/admin/delete", data={"csrf": admin_csrf, "poll_id": poll_id, "poll_token": token, "confirm_name": "Yanlış ad"})
        assert bad.status_code == 409
        good = admin.post("/admin/delete", data={"csrf": admin_csrf, "poll_id": poll_id, "poll_token": token, "confirm_name": "Silinecek oylama"}, follow_redirects=False)
        assert good.status_code == 303
        with connect(db_path) as db:
            assert not rules.active_poll(db)
            for table in ("polls", "participants", "categories", "totals"):
                assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE poll_id=?" if table != "polls" else "SELECT COUNT(*) FROM polls WHERE id=?", (poll_id,)).fetchone()[0] == 0
                assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE poll_id=?" if table != "polls" else "SELECT COUNT(*) FROM polls WHERE id=?", (old_id,)).fetchone()[0] > 0
        created = admin.post("/admin/create", data={"csrf": admin_csrf, "name": "Yeni oylama", "names": "Ada\nBora", "categories": "Style", "mode": "manual"})
        assert created.status_code == 200
        assert voter.get("/vote").status_code == 403
        assert voter.get("/results").status_code == 403
        stale = admin.post(f"/admin/rotate/{people[0]['id']}", data={"csrf": admin_csrf, "poll_id": poll_id, "poll_token": token})
        assert stale.status_code == 409
        stale_delete = admin.post("/admin/delete", data={"csrf": admin_csrf, "poll_id": poll_id, "poll_token": token, "confirm_name": "Silinecek oylama"})
        assert stale_delete.status_code == 409
        with connect(db_path) as db:
            assert rules.active_poll(db)["name"] == "Yeni oylama"


def test_code_rotation_preserves_vote_and_revokes_old_session(db_path):
    poll_id, token, codes, people = create(db_path)
    person_id = people[0]["id"]
    with TestClient(app) as voter, TestClient(app) as admin:
        voter_login(voter, person_id, codes[0][1])
        admin_csrf = admin_login(admin)
        response = admin.post(f"/admin/rotate/{person_id}", data={"csrf": admin_csrf, "poll_id": poll_id, "poll_token": token})
        assert response.status_code == 200
        new_code = re.search(r'id="new-code" value="([^"]+)"', response.text).group(1)
        assert new_code != codes[0][1]
        with connect(db_path) as db:
            assert not rules.authenticate_participant(db, poll_id, person_id, codes[0][1])
            assert rules.authenticate_participant(db, poll_id, person_id, new_code)
            row = db.execute("SELECT code_hash,completed FROM participants WHERE id=?", (person_id,)).fetchone()
            assert row["code_hash"] == rules.hash_code(new_code) and row["completed"] == 0
        assert voter.get("/vote").status_code == 403
        voter_login(voter, person_id, new_code)
        ballot = scores(db_path, poll_id, person_id)
        form = {"csrf": csrf(voter.get("/vote").text), **ballot}
        assert voter.post("/submit", data=form, follow_redirects=False).status_code == 303
        with connect(db_path) as db:
            before = db.execute("SELECT SUM(vote_count) FROM totals WHERE poll_id=?", (poll_id,)).fetchone()[0]
        rotated_again = admin.post(f"/admin/rotate/{person_id}", data={"csrf": admin_csrf, "poll_id": poll_id, "poll_token": token})
        assert rotated_again.status_code == 200
        latest_code = re.search(r'id="new-code" value="([^"]+)"', rotated_again.text).group(1)
        with connect(db_path) as db:
            assert db.execute("SELECT completed FROM participants WHERE id=?", (person_id,)).fetchone()[0] == 1
            assert db.execute("SELECT SUM(vote_count) FROM totals WHERE poll_id=?", (poll_id,)).fetchone()[0] == before
            assert not rules.authenticate_participant(db, poll_id, person_id, new_code)
            assert rules.authenticate_participant(db, poll_id, person_id, latest_code)
        voter_login(voter, person_id, latest_code)
        assert voter.post("/submit", data=form).status_code == 409


def test_existing_database_gains_name_and_session_tags(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE polls(id INTEGER PRIMARY KEY, created_at TEXT, mode TEXT, active INTEGER, revealed INTEGER)")
        db.execute("CREATE TABLE participants(id INTEGER PRIMARY KEY, poll_id INTEGER, name TEXT, code_hash TEXT, completed INTEGER)")
        db.execute("INSERT INTO polls VALUES(1,'2026-01-01','manual',1,0)")
        db.execute("INSERT INTO participants VALUES(1,1,'Ada','hash',0)")
    init(path)
    with connect(path) as db:
        assert rules.active_poll(db)["name"] == "Oylama #1"
        assert rules.active_poll(db)["poll_token"]
        assert db.execute("SELECT auth_tag FROM participants WHERE id=1").fetchone()[0]
