import os
import threading
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("ADMIN_PASSWORD", "test-password-long-enough")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-long-enough-for-tests")
os.environ.setdefault("DATA_DIR", "./data-test")

import pytest
from fastapi.testclient import TestClient

from app import rules
from app.db import connect, init
from app.main import app


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "votes.sqlite3"
    init(path)
    yield path


def setup_poll(path, mode="manual", names="Ada\nBora\nCem"):
    with connect(path) as conn:
        poll_id, codes = rules.create_poll(conn, names, "Style\nAnnoying", mode)
        participants = conn.execute("SELECT id,name FROM participants ORDER BY id").fetchall()
    return poll_id, codes, participants


def scores_for(path, poll_id, voter_id, score=7):
    with connect(path) as conn:
        people, categories = rules.ballot(conn, poll_id, voter_id)
    return {(p["id"], c["id"]): score for p in people for c in categories}


def test_participant_validation_and_code_hash(db):
    with connect(db) as conn:
        with pytest.raises(ValueError):
            rules.create_poll(conn, "Ada", "Style", "manual")
        with pytest.raises(ValueError):
            rules.create_poll(conn, "Ada\nada", "Style", "manual")
    poll, codes, people = setup_poll(db)
    with connect(db) as conn:
        assert rules.authenticate_participant(conn, poll, people[0]["id"], codes[0][1])
        assert not rules.authenticate_participant(conn, poll, people[0]["id"], codes[1][1])
        assert codes[0][1] not in conn.execute("SELECT code_hash FROM participants LIMIT 1").fetchone()[0]


def test_missing_invalid_and_self_vote(db):
    poll, _, people = setup_poll(db)
    voter = people[0]["id"]
    with connect(db) as conn:
        scores = scores_for(db, poll, voter)
        form = {f"score_{a}_{b}": str(value) for (a, b), value in scores.items()}
        assert rules.validate_scores(conn, poll, voter, form) == scores
        with pytest.raises(rules.InvalidVote):
            rules.validate_scores(conn, poll, voter, dict(list(form.items())[1:]))
        with pytest.raises(rules.InvalidVote):
            rules.validate_scores(conn, poll, voter, {**form, next(iter(form)): "11"})
        with pytest.raises(rules.InvalidVote):
            rules.submit_vote(conn, poll, voter, {**scores, (voter, next(iter(scores))[1]): 5})
        assert conn.execute("SELECT SUM(vote_count) FROM totals").fetchone()[0] == 0


def test_duplicate_concurrent_and_n_minus_one(db):
    poll, _, people = setup_poll(db)
    voter = people[0]["id"]
    values = scores_for(db, poll, voter)
    barrier = threading.Barrier(2)

    def send():
        with connect(db) as conn:
            barrier.wait()
            try:
                rules.submit_vote(conn, poll, voter, values)
                return "ok"
            except rules.InvalidVote:
                return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(lambda _: send(), range(2)))
    assert sorted(result) == ["duplicate", "ok"]
    with connect(db) as conn:
        assert conn.execute("SELECT SUM(vote_count) FROM totals").fetchone()[0] == len(values)
        with pytest.raises(ValueError):
            rules.results(conn, poll)
    for person in people[1:]:
        with connect(db) as conn:
            rules.submit_vote(conn, poll, person["id"], scores_for(db, poll, person["id"], 9))
    with connect(db) as conn:
        rules.reveal(conn, poll)
        rows, expected = rules.results(conn, poll)
        assert expected == len(people) - 1
        assert all(row["vote_count"] == expected for row in rows)
        assert all(row["score_sum"] == 9 * expected for row in rows if row["person"] == "Ada")


@pytest.mark.parametrize("mode", ["manual", "automatic"])
def test_reveal_modes(db, mode):
    poll, _, people = setup_poll(db, mode)
    with connect(db) as conn:
        with pytest.raises(ValueError):
            rules.reveal(conn, poll) if mode == "manual" else rules.results(conn, poll)
    for person in people:
        with connect(db) as conn:
            rules.submit_vote(conn, poll, person["id"], scores_for(db, poll, person["id"]))
    with connect(db) as conn:
        assert bool(rules.active_poll(conn)["revealed"]) == (mode == "automatic")
        if mode == "manual":
            rules.reveal(conn, poll)
        assert rules.results(conn, poll)[1] == 2


def test_http_access_and_csrf(tmp_path, monkeypatch):
    path = tmp_path / "web.sqlite3"
    init(path)
    monkeypatch.setattr("app.main.DB_PATH", path)
    poll, codes, people = setup_poll(path)
    with TestClient(app) as client:
        assert client.get("/admin").status_code == 403
        assert client.get("/vote").status_code == 403
        assert client.get("/results").status_code == 403
        assert client.post("/login", data={"person": people[0]["id"], "code": codes[0][1]}).status_code == 403
        token = client.get("/").text.split('name="csrf" value="')[1].split('"')[0]
        assert client.post("/login", data={"csrf": token, "person": people[0]["id"], "code": codes[0][1]}, follow_redirects=False).status_code == 303
        assert client.get("/vote").status_code == 200
        assert client.post("/submit", data={"csrf": token}).status_code == 400
        assert client.get("/results", follow_redirects=False).status_code == 303
