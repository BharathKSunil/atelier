"""Security regression tests for the local Flask API: CSRF token, origin/host
allowlist, and export-destination containment."""

import re

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
    bid = client.post("/api/p/demo/buckets", json={"name": "Candids"}, headers=h).get_json()["id"]
    client.post(f"/api/p/demo/buckets/{bid}/toggle", json={"image_id": 1}, headers=h)
    on = client.post(f"/api/p/demo/buckets/{bid}/toggle", json={"image_id": 2}, headers=h).get_json()
    assert on["in"] is True
    assert client.get("/api/p/demo/buckets").get_json()[0]["count"] == 2
    mem = client.get("/api/p/demo/buckets/for-images?ids=1,2").get_json()
    assert set(mem.keys()) == {"1", "2"}
    client.post(f"/api/p/demo/buckets/{bid}/toggle", json={"image_id": 1}, headers=h)  # toggle off
    assert client.get("/api/p/demo/buckets").get_json()[0]["count"] == 1
    client.delete(f"/api/p/demo/buckets/{bid}", headers=h)
    assert client.get("/api/p/demo/buckets").get_json() == []


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
