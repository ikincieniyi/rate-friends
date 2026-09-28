import math
import os
import re
import xml.etree.ElementTree as ET

os.environ.setdefault("ADMIN_PASSWORD", "test-password-long-enough")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-long-enough-for-tests")
os.environ.setdefault("DATA_DIR", "./data-test")

import pytest
from fastapi.testclient import TestClient

from app import rules
from app.db import connect, init
from app.main import app
from app.results_view import radar_chart, result_cards


def test_radar_scale_and_unrounded_average():
    averages = [1, 10, 22 / 3]
    chart = radar_chart(averages)
    assert chart["dots"][0] == (180, 180)
    assert chart["dots"][1] == chart["axes"][1]
    distance = math.dist((180, 180), chart["dots"][2])
    assert distance == pytest.approx(118 * (22 / 3 - 1) / 9, abs=.001)
    rounded_distance = 118 * (7.33 - 1) / 9
    assert abs(distance - rounded_distance) > .04

    rows = [
        {"person": "Ada", "category": str(i), "score_sum": total, "vote_count": 3}
        for i, total in enumerate((3, 30, 22))
    ]
    card = result_cards(rows)[0]
    assert [item["label"] for item in card["items"]] == ["1.00", "10.00", "7.33"]
    assert card["radar"]["dots"] == chart["dots"]


@pytest.mark.parametrize("count", [1, 2, 3, 9, 10, 11, 30])
def test_results_page_chart_fallback_and_preserved_votes(tmp_path, monkeypatch, count):
    path = tmp_path / "votes.sqlite3"
    init(path)
    monkeypatch.setattr("app.main.DB_PATH", path)
    category_names = ["UzunBaşlık" * 6, "<script>alert(1)</script>"]
    category_names.extend(f"Başlık {i}" for i in range(3, count + 1))
    category_names = category_names[:count]
    with connect(path) as db:
        poll_id, codes = rules.create_poll(db, "Ada\nBora\nCem\nDeniz", "\n".join(category_names), "automatic")
        people = db.execute("SELECT id FROM participants ORDER BY id").fetchall()
        for person, score in zip(people, (1, 4, 8, 10)):
            targets, categories = rules.ballot(db, poll_id, person["id"])
            ballot = {(p["id"], c["id"]): score for p in targets for c in categories}
            rules.submit_vote(db, poll_id, person["id"], ballot)
        tables = ("polls", "participants", "categories", "totals")
        before = {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table}")] for table in tables}

    # Each case represents a separate client, keeping login limits independent.
    with TestClient(app, client=(f"results-{count}", 50000)) as client:
        assert client.get("/results").status_code == 403
        token = re.search(r'name="csrf" value="([^"]+)"', client.get("/").text).group(1)
        response = client.post("/login", data={"csrf": token, "person": people[0]["id"], "code": codes[0][1]}, follow_redirects=False)
        assert response.status_code == 303
        response = client.get("/results")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        html = response.text
        assert html.count('class="card result-card"') == len(people)
        assert html.count('class="result-score"') == len(people) * count
        assert html.count('<strong>7.33</strong>') == count
        assert "UzunBaşlık" * 6 in html
        assert "<script" not in html
        if count >= 2:
            assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

        svgs = re.findall(r'<svg\b.*?</svg>', html, re.DOTALL)
        assert len(svgs) == (len(people) if 3 <= count <= 10 else 0)
        ids = re.findall(r'\bid="([^"]+)"', html)
        assert len(ids) == len(set(ids))
        for svg in svgs:
            root = ET.fromstring(svg)
            assert root.attrib["viewBox"] == "0 0 360 360"
            assert root.attrib["role"] == "img"
            assert all(label in ids for label in root.attrib["aria-labelledby"].split())
            ns = {"svg": "http://www.w3.org/2000/svg"}
            dots = root.findall(".//svg:circle[@class='radar-dot']", ns)
            assert len(dots) == count
            assert root.find("svg:title", ns).text
            assert root.find("svg:desc", ns).text
        if not svgs:
            assert html.count("result-layout-list") == len(people)

    with connect(path) as db:
        after = {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table}")] for table in tables}
        assert after == before
