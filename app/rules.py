import hashlib
import secrets

from .db import transaction

DEFAULT_CATEGORIES = "Shy\nStyle\nSupportive\nConfidence\nAnnoying\nPoliteness\nStupidity\nBoldness\nGood advice"


class InvalidVote(ValueError):
    pass


def lines(raw, minimum, maximum, label):
    values = [part.strip() for part in raw.splitlines() if part.strip()]
    if not minimum <= len(values) <= maximum:
        raise ValueError(f"{label}: {minimum}–{maximum} satır gerekli.")
    if any(len(value) > 60 or any(ord(ch) < 32 for ch in value) for value in values):
        raise ValueError(f"{label}: Her ad en fazla 60 karakter olmalı.")
    if len({value.casefold() for value in values}) != len(values):
        raise ValueError(f"{label}: Tekrarlanan adlar var.")
    return values


def hash_code(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def active_poll(db):
    return db.execute("SELECT * FROM polls WHERE active=1").fetchone()


def progress(db, poll_id):
    row = db.execute("SELECT COUNT(*) n, COALESCE(SUM(completed),0) done FROM participants WHERE poll_id=?", (poll_id,)).fetchone()
    return row["done"], row["n"]


def create_poll(db, names_raw, categories_raw, mode, name="Oylama"):
    names = lines(names_raw, 2, 200, "Katılımcılar")
    categories = lines(categories_raw, 1, 30, "Başlıklar")
    name = name.strip() if isinstance(name, str) else ""
    if not 1 <= len(name) <= 80 or any(ord(ch) < 32 for ch in name):
        raise ValueError("Oylama adı 1–80 karakter olmalı.")
    if mode not in ("manual", "automatic"):
        raise ValueError("Geçersiz açıklama modu.")
    codes = [(name, secrets.token_urlsafe(24)) for name in names]
    with transaction(db):
        prior = active_poll(db)
        if prior:
            done, count = progress(db, prior["id"])
            if not prior["revealed"] or done != count:
                raise ValueError("Aktif oylama bitmeden yenisi oluşturulamaz.")
            db.execute("UPDATE polls SET active=0 WHERE id=?", (prior["id"],))
        poll_id = db.execute("INSERT INTO polls(name,poll_token,mode) VALUES(?,?,?)", (name, secrets.token_urlsafe(24), mode)).lastrowid
        for person_name, code in codes:
            db.execute("INSERT INTO participants(poll_id,name,code_hash,auth_tag) VALUES(?,?,?,?)", (poll_id, person_name, hash_code(code), secrets.token_urlsafe(24)))
        for position, name in enumerate(categories):
            db.execute("INSERT INTO categories(poll_id,name,position) VALUES(?,?,?)", (poll_id, name, position))
        db.execute("INSERT INTO totals(poll_id,target_id,category_id) SELECT ?,p.id,c.id FROM participants p CROSS JOIN categories c WHERE p.poll_id=? AND c.poll_id=?", (poll_id, poll_id, poll_id))
    return poll_id, codes


def delete_poll(db, poll_id, name, poll_token):
    if not isinstance(name, str) or not isinstance(poll_token, str):
        raise ValueError("Oylama onayı geçersiz.")
    with transaction(db):
        poll = active_poll(db)
        if not poll or poll["id"] != poll_id or poll["name"] != name or not secrets.compare_digest(poll["poll_token"], poll_token):
            raise ValueError("Oylama onayı geçersiz veya oylama değişti.")
        db.execute("DELETE FROM totals WHERE poll_id=?", (poll_id,))
        db.execute("DELETE FROM participants WHERE poll_id=?", (poll_id,))
        db.execute("DELETE FROM categories WHERE poll_id=?", (poll_id,))
        db.execute("DELETE FROM polls WHERE id=?", (poll_id,))


def rotate_code(db, poll_id, person_id, poll_token):
    if not isinstance(poll_token, str):
        raise ValueError("Oylama değişti.")
    code = secrets.token_urlsafe(24)
    with transaction(db):
        poll = active_poll(db)
        if not poll or poll["id"] != poll_id or not secrets.compare_digest(poll["poll_token"], poll_token):
            raise ValueError("Aktif oylama bulunamadı.")
        person = db.execute("SELECT name FROM participants WHERE id=? AND poll_id=?", (person_id, poll_id)).fetchone()
        if not person:
            raise ValueError("Katılımcı bulunamadı.")
        db.execute("UPDATE participants SET code_hash=?, auth_tag=? WHERE id=?", (hash_code(code), secrets.token_urlsafe(24), person_id))
    return person["name"], code


def authenticate_participant(db, poll_id, participant_id, code):
    if len(code) > 128:
        return None
    row = db.execute("SELECT * FROM participants WHERE id=? AND poll_id=?", (participant_id, poll_id)).fetchone()
    if not row or not secrets.compare_digest(row["code_hash"], hash_code(code)):
        return None
    return row


def ballot(db, poll_id, voter_id):
    people = db.execute("SELECT id,name FROM participants WHERE poll_id=? AND id<>? ORDER BY id", (poll_id, voter_id)).fetchall()
    categories = db.execute("SELECT id,name FROM categories WHERE poll_id=? ORDER BY position", (poll_id,)).fetchall()
    return people, categories


def validate_scores(db, poll_id, voter_id, form):
    people, categories = ballot(db, poll_id, voter_id)
    if not people or not categories:
        raise InvalidVote("Oylama bulunamadı.")
    expected = {(person["id"], category["id"]) for person in people for category in categories}
    provided = {key for key in form if key.startswith("score_")}
    if provided != {f"score_{target}_{category}" for target, category in expected}:
        raise InvalidVote("Bütün kişiler için bütün başlıkları doldurun.")
    scores = {}
    for target, category in expected:
        raw = form.get(f"score_{target}_{category}")
        if not isinstance(raw, str) or not raw.isascii() or not raw.isdecimal() or str(int(raw)) != raw or not 1 <= int(raw) <= 10:
            raise InvalidVote("Puanlar 1 ile 10 arasında tam sayı olmalı.")
        scores[(target, category)] = int(raw)
    return scores


def submit_vote(db, poll_id, voter_id, scores, expected_auth_tag=None):
    with transaction(db):
        poll = active_poll(db)
        voter = db.execute("SELECT completed,auth_tag FROM participants WHERE id=? AND poll_id=?", (voter_id, poll_id)).fetchone()
        if not poll or poll["id"] != poll_id or poll["revealed"] or not voter or voter["completed"] or (expected_auth_tag is not None and not secrets.compare_digest(voter["auth_tag"], expected_auth_tag)):
            raise InvalidVote("Bu oy artık gönderilemez.")
        expected = {(p["id"], c["id"]) for p in db.execute("SELECT id FROM participants WHERE poll_id=? AND id<>?", (poll_id, voter_id)) for c in db.execute("SELECT id FROM categories WHERE poll_id=?", (poll_id,))}
        if set(scores) != expected or any(type(score) is not int or not 1 <= score <= 10 for score in scores.values()):
            raise InvalidVote("Eksik veya geçersiz oy.")
        for (target, category), score in scores.items():
            changed = db.execute("UPDATE totals SET score_sum=score_sum+?, vote_count=vote_count+1 WHERE poll_id=? AND target_id=? AND category_id=?", (score, poll_id, target, category)).rowcount
            if changed != 1:
                raise InvalidVote("Geçersiz oy hedefi.")
        db.execute("UPDATE participants SET completed=1 WHERE id=? AND completed=0", (voter_id,))
        done, count = progress(db, poll_id)
        if done == count and poll["mode"] == "automatic":
            db.execute("UPDATE polls SET revealed=1 WHERE id=?", (poll_id,))


def reveal(db, poll_id):
    with transaction(db):
        poll = active_poll(db)
        if not poll or poll["id"] != poll_id or poll["mode"] != "manual":
            raise ValueError("Manuel oylama bulunamadı.")
        done, count = progress(db, poll_id)
        if done != count:
            raise ValueError("Herkes oy vermeden sonuçlar açıklanamaz.")
        db.execute("UPDATE polls SET revealed=1 WHERE id=?", (poll_id,))


def results(db, poll_id):
    poll = db.execute("SELECT revealed FROM polls WHERE id=?", (poll_id,)).fetchone()
    if not poll or not poll["revealed"]:
        raise ValueError("Sonuçlar henüz açıklanmadı.")
    done, count = progress(db, poll_id)
    if done != count:
        raise ValueError("Sonuçlar tamamlanmadı.")
    rows = db.execute("SELECT p.name person,c.name category,t.score_sum,t.vote_count FROM totals t JOIN participants p ON p.id=t.target_id JOIN categories c ON c.id=t.category_id WHERE t.poll_id=? ORDER BY p.id,c.position", (poll_id,)).fetchall()
    if any(row["vote_count"] != count - 1 for row in rows):
        raise ValueError("Oy sayısı tutarsız.")
    return rows, count - 1
