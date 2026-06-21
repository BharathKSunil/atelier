"""Project registry: each project is a named source folder + its own SQLite DB.

Layout under <projects_dir>/:
  registry.json        list of {slug, name, source_folder, created_at}
  <slug>.db            per-project database (atelier.db schema)
  <slug>.log           per-project run log
"""

import contextlib
import json
import os
import re
import shutil
import tempfile
import time
import zipfile

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


def set_flags(projects_dir, slug, pinned=None, archived=None):
    """Toggle per-project pinned / archived flags in the registry."""
    items = _load(projects_dir)
    for p in items:
        if p["slug"] == slug:
            if pinned is not None:
                p["pinned"] = bool(pinned)
            if archived is not None:
                p["archived"] = bool(archived)
    _save(projects_dir, items)
    return get_project(projects_dir, slug)


def export_bundle(projects_dir, slug):
    """Write a portable .atelier (zip) of a project into a temp file and return its path.
    Contains a WAL-checkpointed copy of db.sqlite + a manifest (name, source_folder,
    created_at). The DB already holds thumbnails + embeddings, so the bundle is a
    self-contained project. Caller is responsible for cleaning up the temp file."""
    proj = get_project(projects_dir, slug)
    if proj is None:
        raise ValueError("project not found")
    src = db_path(projects_dir, slug)
    if not os.path.exists(src):
        raise ValueError("project database not found")
    # checkpoint the WAL so the single .sqlite file is complete and consistent
    conn = db.connect(src)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    manifest = {
        "atelier_bundle": 1,
        "name": proj.get("name"),
        "source_folder": proj.get("source_folder"),
        "created_at": proj.get("created_at"),
        "schema_version": db.SCHEMA_VERSION,
    }
    fd, tmp = tempfile.mkstemp(prefix=f"{slug}-", suffix=".atelier")
    os.close(fd)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(src, "db.sqlite")
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    return tmp


def _looks_like_atelier_db(path):
    """True iff `path` is a SQLite DB carrying the Atelier schema (an images table)."""
    try:
        conn = db._raw_connect(path)
    except Exception:
        return False
    try:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='images'").fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        conn.close()


def import_bundle(projects_dir, file_path, fallback_name=None, now=None):
    """Register a new project from an exported .atelier zip OR a bare .sqlite/.db file.
    Validates the Atelier schema before adopting it. Returns the new project dict."""
    items = _load(projects_dir)
    existing = {p["slug"] for p in items}
    manifest = {}
    extracted_db = None
    if zipfile.is_zipfile(file_path):
        with zipfile.ZipFile(file_path) as z:
            names = set(z.namelist())
            if "db.sqlite" not in names:
                raise ValueError("bundle is missing db.sqlite")
            if "manifest.json" in names:
                with contextlib.suppress(Exception):
                    manifest = json.loads(z.read("manifest.json"))
            fd, extracted_db = tempfile.mkstemp(suffix=".sqlite")
            os.close(fd)
            with z.open("db.sqlite") as zf, open(extracted_db, "wb") as out:
                shutil.copyfileobj(zf, out)
        db_src = extracted_db
    else:
        db_src = file_path  # a bare .sqlite

    try:
        if not _looks_like_atelier_db(db_src):
            raise ValueError("not an Atelier database (no images table)")
        name = (manifest.get("name") or fallback_name or "Imported project").strip() or "Imported project"
        slug = slugify(name, existing)
        proj = {
            "slug": slug,
            "name": name,
            "source_folder": manifest.get("source_folder") or "",
            "created_at": now if now is not None else time.time(),
            "imported_at": now if now is not None else time.time(),
        }
        os.makedirs(project_dir(projects_dir, slug), exist_ok=True)
        shutil.copyfile(db_src, db_path(projects_dir, slug))
        db.connect(db_path(projects_dir, slug)).close()  # run migrations to the current schema
        items.append(proj)
        _save(projects_dir, items)
        return proj
    finally:
        if extracted_db and os.path.exists(extracted_db):
            with contextlib.suppress(OSError):
                os.remove(extracted_db)


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
