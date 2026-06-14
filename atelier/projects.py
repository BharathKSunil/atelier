"""Project registry: each project is a named source folder + its own SQLite DB.

Layout under <projects_dir>/:
  registry.json        list of {slug, name, source_folder, created_at}
  <slug>.db            per-project database (atelier.db schema)
  <slug>.log           per-project run log
"""

import json
import os
import re
import shutil
import time

from . import db


def _registry_path(projects_dir):
    return os.path.join(projects_dir, "registry.json")


def _load(projects_dir):
    p = _registry_path(projects_dir)
    if not os.path.exists(p):
        return []
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(projects_dir, items):
    os.makedirs(projects_dir, exist_ok=True)
    tmp = _registry_path(projects_dir) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items, f, indent=2)
    os.replace(tmp, _registry_path(projects_dir))


def slugify(name, existing):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
    slug, i = base, 2
    while slug in existing:
        slug = f"{base}-{i}"
        i += 1
    return slug


def project_dir(projects_dir, slug):
    return os.path.join(projects_dir, slug)


def db_path(projects_dir, slug):
    # nested layout: ~/.atelier/<slug>/db.sqlite
    return os.path.join(projects_dir, slug, "db.sqlite")


def log_path(projects_dir, slug):
    return os.path.join(projects_dir, slug, "run.log")


def runs_dir(projects_dir, slug):
    return os.path.join(projects_dir, slug, "runs")


def list_projects(projects_dir):
    return _load(projects_dir)


def get_project(projects_dir, slug):
    for p in _load(projects_dir):
        if p["slug"] == slug:
            return p
    return None


def create_project(projects_dir, name, folder, now=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("project name is required")
    if not folder or not os.path.isdir(folder):
        raise ValueError(f"folder not found: {folder}")
    items = _load(projects_dir)
    slug = slugify(name, {p["slug"] for p in items})
    proj = {
        "slug": slug,
        "name": name,
        "source_folder": os.path.abspath(folder),
        "created_at": now if now is not None else time.time(),
    }
    items.append(proj)
    _save(projects_dir, items)
    os.makedirs(project_dir(projects_dir, slug), exist_ok=True)
    db.init_db(db_path(projects_dir, slug)).close()  # materialize empty DB
    return proj


def register_existing(projects_dir, name, source_folder, now=None):
    """Register a project whose DB will be (or was) built at db_path(slug).
    Returns the project dict (with its assigned slug)."""
    items = _load(projects_dir)
    slug = slugify((name or "project").strip(), {p["slug"] for p in items})
    proj = {
        "slug": slug,
        "name": (name or "project").strip(),
        "source_folder": os.path.abspath(source_folder),
        "created_at": now if now is not None else time.time(),
    }
    items.append(proj)
    _save(projects_dir, items)
    os.makedirs(project_dir(projects_dir, slug), exist_ok=True)
    return proj


def set_params(projects_dir, slug, params):
    items = _load(projects_dir)
    for p in items:
        if p["slug"] == slug:
            p["params"] = params
    _save(projects_dir, items)


def delete_project(projects_dir, slug):
    items = [p for p in _load(projects_dir) if p["slug"] != slug]
    _save(projects_dir, items)
    pdir = project_dir(projects_dir, slug)
    if os.path.isdir(pdir):
        shutil.rmtree(pdir, ignore_errors=True)


def stats(projects_dir, slug):
    path = db_path(projects_dir, slug)
    empty = {"images": 0, "faces": 0, "persons": 0, "series": 0}
    if not os.path.exists(path):
        return empty
    c = db.connect(path)

    def one(q):
        return c.execute(q).fetchone()[0]

    try:
        return {
            "images": one("SELECT COUNT(*) FROM images WHERE processed=1"),
            "faces": one("SELECT COUNT(*) FROM faces"),
            "persons": one("SELECT COUNT(*) FROM persons"),
            "series": one("SELECT COUNT(*) FROM series WHERE frame_count>1"),
        }
    except Exception:
        return empty
    finally:
        c.close()
