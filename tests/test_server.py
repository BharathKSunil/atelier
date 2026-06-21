"""Security regression tests for the local Flask API: CSRF token, origin/host
allowlist, and export-destination containment."""

import re
import time

import pytest

from atelier import db, projects
from atelier.server import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "projects"))


@pytest.fixture
def client(app):
    return app.test_client()


def _token(client):
    html = client.get("/").get_data(as_text=True)
    m = re.search(r'window\.ATELIER_TOKEN="([^"]+)"', html)
    assert m, "token not injected into index.html"
    return m.group(1)


def test_token_is_injected(client):
    assert _token(client)


def test_mutating_request_without_token_is_forbidden(client):
    r = client.post("/api/projects", json={"name": "x", "folder": "/nope"})
    assert r.status_code == 403


def test_mutating_request_with_token_passes_guard(client):
    tok = _token(client)
    r = client.post("/api/projects", json={"name": "x", "folder": "/nope"}, headers={"X-Atelier-Token": tok})
    assert r.status_code == 400  # reaches the handler; rejected on bad folder, not the guard


def test_cross_origin_post_is_blocked(client):
    tok = _token(client)
    r = client.post("/api/projects", json={}, headers={"X-Atelier-Token": tok, "Origin": "http://evil.example"})
    assert r.status_code == 403


def test_non_local_host_is_blocked(client):
    r = client.get("/api/projects", headers={"Host": "192.168.1.50:5050"})
    assert r.status_code == 403


def test_local_get_is_allowed(client):
    assert client.get("/api/projects").status_code == 200


def test_export_rejects_destination_outside_allowed_roots(app, client, tmp_path):
    projects.register_existing(str(tmp_path / "projects"), "demo", str(tmp_path))
    tok = _token(client)
    r = client.post("/api/p/demo/persons/0/export", json={"dest": "/etc/atelier-pwn"}, headers={"X-Atelier-Token": tok})
    assert r.status_code == 400


def test_export_accepts_destination_under_allowed_root(app, client, tmp_path):
    projects.register_existing(str(tmp_path / "projects"), "demo", str(tmp_path))
    tok = _token(client)
    dest = str(tmp_path / "projects" / "out")  # under projects_dir -> allowed
    r = client.post("/api/p/demo/persons/0/export", json={"dest": dest}, headers={"X-Atelier-Token": tok})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_export_persons_unions_images_and_contains_dest(app, client, tmp_path):
    pdir = str(tmp_path / "projects")
    projects.register_existing(pdir, "demo", str(tmp_path))
    src = tmp_path / "src"
    src.mkdir()
    c = db.connect(projects.db_path(pdir, "demo"))
    for i in (1, 2, 3):  # person 1 -> images 1,2 ; person 2 -> image 3
        f = src / f"{i}.jpg"
        f.write_bytes(b"x")
        c.execute("INSERT INTO images(id, path, processed) VALUES(?,?,1)", (i, str(f)))
        c.execute("INSERT INTO faces(id, image_id, person_id) VALUES(?,?,?)", (i, i, 1 if i < 3 else 2))
    c.commit()
    c.close()
    tok = _token(client)
    dest = str(tmp_path / "projects" / "combined")
    r = client.post("/api/p/demo/persons/export", json={"ids": [1, 2], "dest": dest}, headers={"X-Atelier-Token": tok})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] and body["count"] == 3  # union of both people's images, deduped
    bad = client.post(
        "/api/p/demo/persons/export", json={"ids": [1], "dest": "/etc/x"}, headers={"X-Atelier-Token": tok}
    )
    assert bad.status_code == 400  # containment still enforced


def test_buckets_crud_toggle_and_membership(app, client, tmp_path):
    pdir = str(tmp_path / "projects")
    projects.register_existing(pdir, "demo", str(tmp_path))
    c = db.connect(projects.db_path(pdir, "demo"))
    for i in (1, 2):
        c.execute("INSERT INTO images(id, path, processed) VALUES(?,?,1)", (i, f"/p{i}.jpg"))
    c.commit()
    c.close()
    h = {"X-Atelier-Token": _token(client)}

    def candids():  # the project also has the default "Print list" bucket now
        return next(b for b in client.get("/api/p/demo/buckets").get_json() if b["id"] == bid)

    bid = client.post("/api/p/demo/buckets", json={"name": "Candids"}, headers=h).get_json()["id"]
    client.post(f"/api/p/demo/buckets/{bid}/toggle", json={"image_id": 1}, headers=h)
    on = client.post(f"/api/p/demo/buckets/{bid}/toggle", json={"image_id": 2}, headers=h).get_json()
    assert on["in"] is True
    assert candids()["count"] == 2
    mem = client.get("/api/p/demo/buckets/for-images?ids=1,2").get_json()
    assert set(mem.keys()) == {"1", "2"}
    client.post(f"/api/p/demo/buckets/{bid}/toggle", json={"image_id": 1}, headers=h)  # toggle off
    assert candids()["count"] == 1
    client.delete(f"/api/p/demo/buckets/{bid}", headers=h)
    assert all(b["id"] != bid for b in client.get("/api/p/demo/buckets").get_json())  # Candids gone


def test_bucket_add_people_unions_their_photos(app, client, tmp_path):
    pdir = str(tmp_path / "projects")
    projects.register_existing(pdir, "demo", str(tmp_path))
    c = db.connect(projects.db_path(pdir, "demo"))
    for i in (1, 2, 3):
        c.execute("INSERT INTO images(id, path, processed) VALUES(?,?,1)", (i, f"/p{i}.jpg"))
    # person 1 -> images 1,2 ; person 2 -> images 2,3 (image 2 shared)
    c.executemany(
        "INSERT INTO faces(id, image_id, person_id) VALUES(?,?,?)",
        [(1, 1, 1), (2, 2, 1), (3, 2, 2), (4, 3, 2)],
    )
    c.commit()
    c.close()
    h = {"X-Atelier-Token": _token(client)}
    bid = client.post("/api/p/demo/buckets", json={"name": "Family"}, headers=h).get_json()["id"]
    r = client.post(f"/api/p/demo/buckets/{bid}/add-people", json={"person_ids": [1]}, headers=h).get_json()
    assert r["added"] == 2  # person 1 is in images 1 and 2
    client.post(f"/api/p/demo/buckets/{bid}/add-people", json={"person_ids": [2]}, headers=h)  # adds image 3
    assert client.get(f"/api/p/demo/buckets/{bid}/images").get_json()["total"] == 3  # union, deduped
    bad = client.post("/api/p/demo/buckets/999/add-people", json={"person_ids": [1]}, headers=h)
    assert bad.status_code == 404


def test_bucket_toggle_validates_bucket_and_image_id(app, client, tmp_path):
    pdir = str(tmp_path / "projects")
    projects.register_existing(pdir, "demo", str(tmp_path))
    c = db.connect(projects.db_path(pdir, "demo"))
    c.execute("INSERT INTO images(id, path, processed) VALUES(1, '/p1.jpg', 1)")
    c.commit()
    c.close()
    h = {"X-Atelier-Token": _token(client)}
    stale = client.post("/api/p/demo/buckets/999/toggle", json={"image_id": 1}, headers=h)
    assert stale.status_code == 404  # nonexistent bucket -> clean 404, not a 500 FK error
    bid = client.post("/api/p/demo/buckets", json={"name": "B"}, headers=h).get_json()["id"]
    bad = client.post(f"/api/p/demo/buckets/{bid}/toggle", json={"image_id": "x"}, headers=h)
    assert bad.status_code == 400  # non-numeric image_id -> 400, not a 500 ValueError


def test_rerun_fresh_destroys_everything_and_starts_run(app, client, tmp_path, monkeypatch):
    """F4: 'Start over' wipes the whole project DB (faces/persons/buckets and all) and
    re-runs from scratch. Faked subprocess so no ML stack is needed."""
    from atelier import runner

    class FakeProc:
        def __init__(self, *a, **k):
            self.stdout = iter(["ok"])
            self.returncode = 0

        def wait(self):
            pass

        def terminate(self):
            pass

    runner._runners.clear()  # avoid a stale cached runner from another test
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: FakeProc())

    pdir = str(tmp_path / "projects")
    src = tmp_path / "src"
    src.mkdir()
    projects.register_existing(pdir, "demo", str(src))
    c = db.connect(projects.db_path(pdir, "demo"))
    c.execute("INSERT INTO images(id, path, processed) VALUES(1, '/p1.jpg', 1)")
    c.execute("INSERT INTO persons(id, display_name) VALUES(0, 'Amara')")
    c.execute("INSERT INTO faces(id, image_id, person_id) VALUES(1, 1, 0)")
    c.execute("INSERT INTO buckets(name) VALUES('Keep')")
    c.commit()
    c.close()

    h = {"X-Atelier-Token": _token(client)}
    r = client.post("/api/p/demo/rerun-fresh", json={}, headers=h)
    assert r.status_code == 200 and r.get_json()["ok"]

    rn = runner.get_runner("demo", projects.db_path(pdir, "demo"))
    t0 = time.time()
    while rn.state["running"] and time.time() - t0 < 5:
        time.sleep(0.02)
    c = db.connect(projects.db_path(pdir, "demo"))
    counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("images", "faces", "persons")}
    # a fresh DB re-seeds only the default "Print list" bucket (print list is a bucket now)
    bks = c.execute("SELECT name, role FROM buckets").fetchall()
    c.close()
    assert counts == {"images": 0, "faces": 0, "persons": 0}  # truly destroyed
    assert len(bks) == 1 and bks[0]["role"] == "print"


def test_review_set_filters_solo_group_and_multi(app, client, tmp_path):
    """F2/F3: review-set partitions a person's photos (solo/group) and matches
    multi-person sets (together = all present; only = exactly these people)."""
    pdir = str(tmp_path / "projects")
    projects.register_existing(pdir, "demo", str(tmp_path))
    c = db.connect(projects.db_path(pdir, "demo"))
    for i in (1, 2, 3, 4):
        c.execute("INSERT INTO images(id, path, processed) VALUES(?,?,1)", (i, f"/p{i}.jpg"))
    # img1: {1}; img2: {1,2}; img3: {1,2,3}; img4: {2,3}
    c.executemany(
        "INSERT INTO faces(image_id, person_id) VALUES(?,?)",
        [(1, 1), (2, 1), (2, 2), (3, 1), (3, 2), (3, 3), (4, 2), (4, 3)],
    )
    c.commit()
    c.close()

    def ids(qs):
        return sorted(r["id"] for r in client.get(f"/api/p/demo/review-set?{qs}").get_json())

    assert ids("person=1&mode=solo") == [1]  # person 1 alone
    assert ids("person=1&mode=group") == [2, 3]  # person 1 with others
    assert ids("persons=1,2&mode=together") == [2, 3]  # both present (others ok)
    assert ids("persons=1,2&mode=only") == [2]  # exactly {1,2}
    assert ids("persons=2,3&mode=together") == [3, 4]
    assert ids("persons=2,3&mode=only") == [4]  # img3 also has person 1 -> excluded


def test_print_list_is_the_default_bucket(app, client, tmp_path):
    """The print list is just the project's default bucket: star toggles membership of
    it, /prints lists it, and a fresh project already has it (role='print')."""
    pdir = str(tmp_path / "projects")
    projects.register_existing(pdir, "demo", str(tmp_path))
    c = db.connect(projects.db_path(pdir, "demo"))
    c.execute("INSERT INTO images(id, path, processed) VALUES(1, '/p1.jpg', 1)")
    c.commit()
    c.close()
    h = {"X-Atelier-Token": _token(client)}
    default = next(b for b in client.get("/api/p/demo/buckets").get_json() if b["is_default"])
    assert default["role"] == "print"

    r = client.post("/api/p/demo/star/1", json={}, headers=h).get_json()
    assert r["starred"] is True and r["bucket_id"] == default["id"]
    assert client.get("/api/p/demo/prints").get_json()["total"] == 1
    assert next(b for b in client.get("/api/p/demo/buckets").get_json() if b["is_default"])["count"] == 1

    r2 = client.post("/api/p/demo/star/1", json={}, headers=h).get_json()  # toggles off
    assert r2["starred"] is False
    assert client.get("/api/p/demo/prints").get_json()["total"] == 0


def test_set_default_bucket_repoints_spacebar(app, client, tmp_path):
    pdir = str(tmp_path / "projects")
    projects.register_existing(pdir, "demo", str(tmp_path))
    c = db.connect(projects.db_path(pdir, "demo"))
    c.execute("INSERT INTO images(id, path, processed) VALUES(1, '/p1.jpg', 1)")
    c.commit()
    c.close()
    h = {"X-Atelier-Token": _token(client)}
    bid = client.post("/api/p/demo/buckets", json={"name": "Album"}, headers=h).get_json()["id"]
    assert client.post(f"/api/p/demo/buckets/{bid}/set-default", json={}, headers=h).status_code == 200
    # star now lands in Album
    r = client.post("/api/p/demo/star/1", json={}, headers=h).get_json()
    assert r["bucket_id"] == bid
    defaults = [b for b in client.get("/api/p/demo/buckets").get_json() if b["is_default"]]
    assert len(defaults) == 1 and defaults[0]["id"] == bid  # exactly one default


def test_bucket_delete_cascades_items(app, client, tmp_path):
    pdir = str(tmp_path / "projects")
    projects.register_existing(pdir, "demo", str(tmp_path))
    c = db.connect(projects.db_path(pdir, "demo"))
    c.execute("INSERT INTO images(id, path, processed) VALUES(1, '/p1.jpg', 1)")
    c.commit()
    c.close()
    h = {"X-Atelier-Token": _token(client)}
    bid = client.post("/api/p/demo/buckets", json={"name": "B"}, headers=h).get_json()["id"]
    client.post(f"/api/p/demo/buckets/{bid}/toggle", json={"image_id": 1}, headers=h)
    client.delete(f"/api/p/demo/buckets/{bid}", headers=h)
    c = db.connect(projects.db_path(pdir, "demo"))
    left = c.execute("SELECT COUNT(*) FROM bucket_items WHERE bucket_id=?", (bid,)).fetchone()[0]
    c.close()
    assert left == 0  # ON DELETE CASCADE removed the membership rows
