"""Security regression tests for the local Flask API: CSRF token, origin/host
allowlist, and export-destination containment."""

import re

import pytest

from atelier import projects
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
