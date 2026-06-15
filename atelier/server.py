#!/usr/bin/env python3
"""Phase 4 — Browse. Project-centric Flask REST API + static SPA.

Each project owns its own SQLite DB (see atelier.projects). The dashboard
creates projects, a native macOS dialog picks the source folder, the pipeline
runs in the background with a live console, and People/Series/Faces are browsed
per project.
"""

import argparse
import io
import json
import os
import secrets
import shutil
import sqlite3
import time
from urllib.parse import urlparse

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    request,
    send_file,
    send_from_directory,
    stream_with_context,
)
from werkzeug.exceptions import HTTPException

from atelier import config, db, fsdialog, migrate, overrides, projects, settings
from atelier.runner import get_runner

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

# Loopback hostnames the server will answer to. The app is unauthenticated by
# design (single local user); these checks keep a stray LAN bind or a drive-by
# cross-origin page from reaching the API.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _copy_unique(paths, dest):
    """Copy each existing source into dest, de-duping colliding basenames so two
    sources that share a filename don't silently overwrite. Returns the count copied."""
    used = set()
    n = 0
    for p in paths:
        if not os.path.exists(p):
            continue
        stem, ext = os.path.splitext(os.path.basename(p))
        name, i = stem + ext, 1
        while name in used or os.path.exists(os.path.join(dest, name)):
            name = f"{stem}_{i}{ext}"
            i += 1
        used.add(name)
        try:
            shutil.copy2(p, os.path.join(dest, name))
            n += 1
        except OSError:
            pass
    return n


def create_app(projects_dir):
    app = Flask(__name__, static_folder=None)
    os.makedirs(projects_dir, exist_ok=True)
    # one-time migration: flat ./projects -> nested ~/.atelier on first launch
    if not os.path.exists(os.path.join(projects_dir, "registry.json")):
        n = migrate.migrate_flat_to_nested("projects", projects_dir)
        if n:
            print(f"migrated {n} project(s) from ./projects -> {projects_dir}")

    # Per-process CSRF token. Injected into index.html and required on every
    # state-changing request; a cross-origin page can POST but cannot read it.
    app_token = secrets.token_urlsafe(32)

    @app.before_request
    def _guard():
        host = (request.host or "").rsplit(":", 1)[0].strip("[]")
        if host not in LOCAL_HOSTS:
            abort(403, description="non-local host")
        origin = request.headers.get("Origin")
        if origin and (urlparse(origin).hostname or "") not in LOCAL_HOSTS:
            abort(403, description="cross-origin request blocked")
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            tok = request.headers.get("X-Atelier-Token", "")
            if not secrets.compare_digest(tok, app_token):
                abort(403, description="missing or invalid request token")

    # ----- helpers -----
    def _allowed_roots():
        roots = []
        for r in (os.path.expanduser("~"), projects_dir, "/Volumes", "/tmp", "/private/tmp", "/mnt", "/media"):
            try:
                rp = os.path.realpath(r)
            except OSError:
                continue
            if os.path.isdir(rp):
                roots.append(rp)
        return roots

    def _safe_dest(dest):
        """Resolve an export destination and confine it to a sane root (home,
        the projects dir, mounted volumes, tmp). Returns the real path or None."""
        if not dest:
            return None
        real = os.path.realpath(os.path.expanduser(str(dest)))
        for root in _allowed_roots():
            if real == root or real.startswith(root + os.sep):
                return real
        return None

    def _require(slug):
        proj = projects.get_project(projects_dir, slug)
        if not proj:
            abort(404, description=f"no project '{slug}'")
        return proj

    def _conn(slug):
        return db.connect(projects.db_path(projects_dir, slug))

    def _runner(slug):
        return get_runner(
            slug,
            projects.db_path(projects_dir, slug),
            projects.log_path(projects_dir, slug),
            projects.runs_dir(projects_dir, slug),
        )

    def _page():
        try:
            offset = max(0, int(request.args.get("offset", 0)))
        except ValueError:
            offset = 0
        try:
            limit = min(500, max(1, int(request.args.get("limit", 60))))
        except ValueError:
            limit = 60
        return offset, limit

    def _paged(items, total, offset, limit):
        nxt = offset + limit if offset + limit < total else None
        return jsonify(items=items, total=total, next_offset=nxt)

    # ----- static -----
    @app.get("/")
    def index():
        with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as f:
            html = f.read()
        tag = f"<script>window.ATELIER_TOKEN={json.dumps(app_token)};</script>"
        html = html.replace("</head>", tag + "</head>", 1)
        return Response(html, mimetype="text/html")

    @app.get("/static/<path:fname>")
    def static_files(fname):
        return send_from_directory(WEB_DIR, fname)

    @app.get("/favicon.ico")
    def favicon():
        return ("", 204)

    # ----- filesystem (native dialog) -----
    @app.post("/api/fs/choose")
    def fs_choose():
        default = (request.json or {}).get("default")
        path = fsdialog.choose_folder(default)
        if not path:
            unavailable = not fsdialog.available()
            msg = "native folder picker is macOS-only — type or paste the folder path" if unavailable else "cancelled"
            return jsonify(ok=False, msg=msg, unavailable=unavailable), 200
        return jsonify(ok=True, path=path, exists=os.path.isdir(path))

    @app.post("/api/fs/reveal")
    def fs_reveal():
        path = (request.json or {}).get("path", "")
        return jsonify(ok=fsdialog.reveal(path))

    # ----- projects -----
    @app.get("/api/projects")
    def list_projects():
        out = []
        for p in projects.list_projects(projects_dir):
            item = dict(p)
            item["stats"] = projects.stats(projects_dir, p["slug"])
            item["running"] = _runner(p["slug"]).state["running"]
            item["cover"] = []
            try:
                c = _conn(p["slug"])
                item["cover"] = [
                    r[0]
                    for r in c.execute(
                        """SELECT id FROM images WHERE processed=1 AND thumbnail IS NOT NULL
                       ORDER BY print_score DESC LIMIT 5"""
                    )
                ]
                if not item["cover"]:
                    item["cover"] = [r[0] for r in c.execute("SELECT id FROM images WHERE processed=1 LIMIT 5")]
                c.close()
            except Exception:
                pass
            out.append(item)
        return jsonify(out)

    @app.post("/api/projects")
    def create_project():
        body = request.json or {}
        try:
            proj = projects.create_project(projects_dir, body.get("name"), body.get("folder"))
        except ValueError as e:
            return jsonify(ok=False, msg=str(e)), 400
        flags = settings.phase_flags(settings.load(projects_dir, proj["slug"]))
        ok, msg = _runner(proj["slug"]).start(proj["source_folder"], flags=flags)
        return jsonify(ok=True, project=proj, run_started=ok, run_msg=msg)

    @app.delete("/api/projects/<slug>")
    def delete_project(slug):
        _require(slug)
        if _runner(slug).state["running"]:
            return jsonify(ok=False, msg="stop the run before deleting"), 409
        projects.delete_project(projects_dir, slug)
        return jsonify(ok=True)

    # ----- run control -----
    @app.post("/api/p/<slug>/run")
    def run_start(slug):
        proj = _require(slug)
        body = request.json or {}
        folder = body.get("folder") or proj["source_folder"]
        flags = settings.phase_flags(settings.load(projects_dir, slug))
        phases = settings.PHASES_FOR.get(body.get("affects"))  # None -> full pipeline
        ok, msg = _runner(slug).start(folder, phases=phases, flags=flags)
        return jsonify(ok=ok, msg=msg), (200 if ok else 409)

    @app.get("/api/p/<slug>/settings")
    def get_settings(slug):
        _require(slug)
        return jsonify(spec=settings.spec_json(), values=settings.load(projects_dir, slug))

    @app.route("/api/p/<slug>/settings", methods=["PUT"])
    def put_settings(slug):
        _require(slug)
        vals = settings.save(projects_dir, slug, (request.json or {}).get("values") or {})
        return jsonify(ok=True, values=vals)

    @app.get("/api/p/<slug>/run/status")
    def run_status(slug):
        _require(slug)
        return jsonify(_runner(slug).status())

    @app.post("/api/p/<slug>/run/stop")
    def run_stop(slug):
        _require(slug)
        ok, msg = _runner(slug).cancel()
        return jsonify(ok=ok, msg=msg), (200 if ok else 409)

    def _since():
        try:
            return int(request.args.get("since", 0))
        except ValueError:
            return 0

    @app.get("/api/p/<slug>/run/log")
    def run_log(slug):
        _require(slug)
        return jsonify(lines=_runner(slug).log_lines(since=_since()))

    @app.get("/api/p/<slug>/run/stream")
    def run_stream(slug):
        _require(slug)
        r, since = _runner(slug), _since()

        def gen():
            yield "retry: 3000\n\n"
            for n, t in r.stream(since=since):
                yield f"id: {n}\ndata: {json.dumps(t)}\n\n"
            yield "event: end\ndata: {}\n\n"

        return Response(
            stream_with_context(gen()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/p/<slug>/runs")
    def runs_list(slug):
        _require(slug)
        return jsonify(_runner(slug).runs())

    @app.get("/api/p/<slug>/runs/<int:rid>/log")
    def run_history_log(slug, rid):
        _require(slug)
        path = _runner(slug).run_log_path(rid)
        if not path or not os.path.exists(path):
            abort(404)
        with open(path, encoding="utf-8", errors="replace") as f:
            return Response(f.read(), mimetype="text/plain")

    # ----- stats -----
    @app.get("/api/p/<slug>/stats")
    def stats(slug):
        _require(slug)
        return jsonify(projects.stats(projects_dir, slug))

    # ----- persons -----
    @app.get("/api/p/<slug>/persons")
    def persons(slug):
        _require(slug)
        c = _conn(slug)
        offset, limit = _page()
        q = (request.args.get("q") or "").strip()
        where = ""
        params = []
        if q:
            where = "WHERE p.display_name LIKE '%'||?||'%' COLLATE NOCASE"
            params.append(q)
        total = c.execute(f"SELECT COUNT(*) FROM persons p {where}", params).fetchone()[0]
        rows = c.execute(
            f"""SELECT p.id, p.display_name, COUNT(f.id) cnt,
                 (SELECT id FROM faces WHERE person_id=p.id
                  ORDER BY is_best DESC, quality_score DESC LIMIT 1) best_face
               FROM persons p LEFT JOIN faces f ON f.person_id=p.id
               {where}
               GROUP BY p.id ORDER BY cnt DESC LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()
        return _paged([dict(r) for r in rows], total, offset, limit)

    @app.get("/api/p/<slug>/persons/<int:pid>/faces")
    def person_faces(slug, pid):
        _require(slug)
        c = _conn(slug)
        offset, limit = _page()
        total = c.execute("SELECT COUNT(*) FROM faces WHERE person_id=?", (pid,)).fetchone()[0]
        rows = c.execute(
            """SELECT f.id, f.image_id, f.quality_score, f.is_best, i.path
               FROM faces f JOIN images i ON i.id=f.image_id
               WHERE f.person_id=? ORDER BY f.is_best DESC, f.quality_score DESC
               LIMIT ? OFFSET ?""",
            (pid, limit, offset),
        ).fetchall()
        return _paged([dict(r) for r in rows], total, offset, limit)

    @app.post("/api/p/<slug>/persons/<int:pid>/rename")
    def rename(slug, pid):
        _require(slug)
        overrides.set_group_name(_conn(slug), pid, (request.json or {}).get("name", ""))
        return jsonify(ok=True)

    @app.post("/api/p/<slug>/persons/merge")
    def merge_persons(slug):
        _require(slug)
        body = request.json or {}
        frm, into = body.get("from_id"), body.get("into_id")
        if frm is None or into is None or frm == into:
            return jsonify(ok=False, msg="need distinct from_id / into_id"), 400
        overrides.merge_persons(_conn(slug), int(frm), int(into))
        return jsonify(ok=True)

    @app.post("/api/p/<slug>/persons/<int:pid>/split")
    def split_person(slug, pid):
        _require(slug)
        body = request.json or {}
        face_ids = body.get("face_ids") or []
        if not face_ids:
            return jsonify(ok=False, msg="no faces selected"), 400
        name = (body.get("name") or "").strip() or None
        gk = overrides.split_person(_conn(slug), [int(x) for x in face_ids], name=name)
        return jsonify(ok=True, group=gk)

    @app.post("/api/p/<slug>/faces/<int:fid>/reassign")
    def reassign_face(slug, fid):
        _require(slug)
        pid = (request.json or {}).get("person_id")
        if pid is None:
            return jsonify(ok=False, msg="need person_id"), 400
        overrides.reassign_face(_conn(slug), fid, int(pid))
        return jsonify(ok=True)

    @app.post("/api/p/<slug>/faces/reject")
    def reject_faces(slug):
        _require(slug)
        ids = (request.json or {}).get("face_ids") or []
        n = overrides.reject_faces(_conn(slug), ids)
        return jsonify(ok=True, removed=n)

    @app.get("/api/p/<slug>/faces/<int:fid>/similar")
    def similar_faces(slug, fid):
        _require(slug)
        try:
            pid = int(request.args.get("person", -1))
            thr = float(request.args.get("threshold", 0.5))
        except ValueError:
            return jsonify(ok=False, msg="bad params"), 400
        sims = overrides.similar_faces_in_person(_conn(slug), fid, pid, threshold=thr)
        return jsonify([{"id": i, "cosine": round(c, 3)} for i, c in sims])

    @app.post("/api/p/<slug>/persons/<int:pid>/export")
    def export_person(slug, pid):
        _require(slug)
        dest = _safe_dest((request.json or {}).get("dest"))
        if not dest:
            return jsonify(ok=False, msg="choose a valid destination folder"), 400
        c = _conn(slug)
        paths = [
            r["path"]
            for r in c.execute(
                """SELECT DISTINCT i.path FROM images i JOIN faces f ON f.image_id=i.id
               WHERE f.person_id=?""",
                (pid,),
            )
        ]
        os.makedirs(dest, exist_ok=True)
        n = _copy_unique(paths, dest)
        return jsonify(ok=True, count=n, total=len(paths), dest=dest)

    @app.post("/api/p/<slug>/persons/export")
    def export_persons(slug):
        """Copy the originals of every image that ANY of the given people appear in
        into one folder (deduped) — for zipping and sharing."""
        _require(slug)
        body = request.json or {}
        ids = [int(x) for x in (body.get("ids") or [])]
        dest = _safe_dest(body.get("dest"))
        if not ids:
            return jsonify(ok=False, msg="no people selected"), 400
        if not dest:
            return jsonify(ok=False, msg="choose a valid destination folder"), 400
        c = _conn(slug)
        ph = ",".join("?" * len(ids))
        paths = [
            r["path"]
            for r in c.execute(
                f"""SELECT DISTINCT i.path FROM images i JOIN faces f ON f.image_id=i.id
                    WHERE f.person_id IN ({ph})""",
                ids,
            )
        ]
        os.makedirs(dest, exist_ok=True)
        n = _copy_unique(paths, dest)
        return jsonify(ok=True, count=n, total=len(paths), dest=dest)

    # ----- buckets (user-defined collections; an image can be in many) -----
    _BUCKET_COLORS = ["#c64a5b", "#cda35c", "#5c9ec6", "#6cae72", "#a76cc6", "#c68a5c"]

    @app.get("/api/p/<slug>/buckets")
    def buckets_list(slug):
        _require(slug)
        rows = (
            _conn(slug)
            .execute(
                """SELECT b.id, b.name, b.color, b.sort_order,
                      (SELECT COUNT(*) FROM bucket_items WHERE bucket_id=b.id) AS count
               FROM buckets b ORDER BY b.sort_order, b.id"""
            )
            .fetchall()
        )
        return jsonify([dict(r) for r in rows])

    @app.post("/api/p/<slug>/buckets")
    def bucket_create(slug):
        _require(slug)
        name = ((request.json or {}).get("name") or "").strip()
        if not name:
            return jsonify(ok=False, msg="bucket name is required"), 400
        c = _conn(slug)
        n = c.execute("SELECT COUNT(*) FROM buckets").fetchone()[0]
        color = (request.json or {}).get("color") or _BUCKET_COLORS[n % len(_BUCKET_COLORS)]
        cur = c.execute(
            "INSERT INTO buckets(name, color, sort_order, created_at) VALUES(?,?,?,?)",
            (name, color, n, time.time()),
        )
        c.commit()
        return jsonify(ok=True, id=cur.lastrowid, color=color)

    @app.put("/api/p/<slug>/buckets/<int:bid>")
    def bucket_update(slug, bid):
        _require(slug)
        body = request.json or {}
        c = _conn(slug)
        if "name" in body:
            nm = (body.get("name") or "").strip()
            if not nm:
                return jsonify(ok=False, msg="name required"), 400
            c.execute("UPDATE buckets SET name=? WHERE id=?", (nm, bid))
        if "color" in body:
            c.execute("UPDATE buckets SET color=? WHERE id=?", (body.get("color"), bid))
        c.commit()
        return jsonify(ok=True)

    @app.delete("/api/p/<slug>/buckets/<int:bid>")
    def bucket_delete(slug, bid):
        _require(slug)
        c = _conn(slug)
        c.execute("DELETE FROM bucket_items WHERE bucket_id=?", (bid,))
        c.execute("DELETE FROM buckets WHERE id=?", (bid,))
        c.commit()
        return jsonify(ok=True)

    def _bucket_count(c, bid):
        return c.execute("SELECT COUNT(*) FROM bucket_items WHERE bucket_id=?", (bid,)).fetchone()[0]

    def _bucket_exists(c, bid):
        return c.execute("SELECT 1 FROM buckets WHERE id=?", (bid,)).fetchone() is not None

    @app.post("/api/p/<slug>/buckets/<int:bid>/toggle")
    def bucket_toggle(slug, bid):
        _require(slug)
        try:
            iid = int((request.json or {}).get("image_id"))
        except (TypeError, ValueError):
            return jsonify(ok=False, msg="need image_id"), 400
        c = _conn(slug)
        if not _bucket_exists(c, bid):
            return jsonify(ok=False, msg="no such bucket"), 404
        exists = c.execute("SELECT 1 FROM bucket_items WHERE bucket_id=? AND image_id=?", (bid, iid)).fetchone()
        if exists:
            c.execute("DELETE FROM bucket_items WHERE bucket_id=? AND image_id=?", (bid, iid))
            inb = False
        else:
            c.execute(
                "INSERT OR IGNORE INTO bucket_items(bucket_id, image_id, added_at) VALUES(?,?,?)",
                (bid, iid, time.time()),
            )
            inb = True
        c.commit()
        return jsonify({"ok": True, "in": inb})

    @app.post("/api/p/<slug>/buckets/<int:bid>/add")
    def bucket_add_many(slug, bid):
        _require(slug)
        try:
            ids = [int(x) for x in ((request.json or {}).get("image_ids") or [])]
        except (TypeError, ValueError):
            return jsonify(ok=False, msg="bad image_ids"), 400
        if not ids:
            return jsonify(ok=False, msg="no images"), 400
        c = _conn(slug)
        if not _bucket_exists(c, bid):
            return jsonify(ok=False, msg="no such bucket"), 404
        before = _bucket_count(c, bid)
        now = time.time()
        c.executemany(
            "INSERT OR IGNORE INTO bucket_items(bucket_id, image_id, added_at) VALUES(?,?,?)",
            [(bid, i, now) for i in ids],
        )
        c.commit()
        return jsonify(ok=True, added=_bucket_count(c, bid) - before)

    @app.post("/api/p/<slug>/buckets/<int:bid>/add-people")
    def bucket_add_people(slug, bid):
        """Add every photo the given people appear in to the bucket (by face)."""
        _require(slug)
        pids = [int(x) for x in ((request.json or {}).get("person_ids") or [])]
        if not pids:
            return jsonify(ok=False, msg="no people selected"), 400
        c = _conn(slug)
        if not _bucket_exists(c, bid):
            return jsonify(ok=False, msg="no such bucket"), 404
        ph = ",".join("?" * len(pids))
        img_ids = [
            r["image_id"] for r in c.execute(f"SELECT DISTINCT image_id FROM faces WHERE person_id IN ({ph})", pids)
        ]
        before = _bucket_count(c, bid)
        now = time.time()
        c.executemany(
            "INSERT OR IGNORE INTO bucket_items(bucket_id, image_id, added_at) VALUES(?,?,?)",
            [(bid, i, now) for i in img_ids],
        )
        c.commit()
        return jsonify(ok=True, added=_bucket_count(c, bid) - before)

    @app.get("/api/p/<slug>/buckets/for-images")
    def buckets_for_images(slug):
        _require(slug)
        ids = [int(x) for x in request.args.get("ids", "").split(",") if x.strip().isdigit()]
        if not ids:
            return jsonify({})
        ph = ",".join("?" * len(ids))
        out = {}
        for r in _conn(slug).execute(f"SELECT image_id, bucket_id FROM bucket_items WHERE image_id IN ({ph})", ids):
            out.setdefault(str(r["image_id"]), []).append(r["bucket_id"])
        return jsonify(out)

    @app.get("/api/p/<slug>/buckets/<int:bid>/images")
    def bucket_images(slug, bid):
        _require(slug)
        c = _conn(slug)
        offset, limit = _page()
        total = c.execute("SELECT COUNT(*) FROM bucket_items WHERE bucket_id=?", (bid,)).fetchone()[0]
        rows = c.execute(
            """SELECT i.id, i.path, i.print_score FROM bucket_items bi
               JOIN images i ON i.id=bi.image_id WHERE bi.bucket_id=?
               ORDER BY bi.added_at DESC, i.id LIMIT ? OFFSET ?""",
            (bid, limit, offset),
        ).fetchall()
        return _paged([dict(r) for r in rows], total, offset, limit)

    @app.post("/api/p/<slug>/buckets/<int:bid>/export")
    def bucket_export(slug, bid):
        _require(slug)
        dest = _safe_dest((request.json or {}).get("dest"))
        if not dest:
            return jsonify(ok=False, msg="choose a valid destination folder"), 400
        c = _conn(slug)
        paths = [
            r["path"]
            for r in c.execute(
                "SELECT i.path FROM bucket_items bi JOIN images i ON i.id=bi.image_id WHERE bi.bucket_id=?",
                (bid,),
            )
        ]
        os.makedirs(dest, exist_ok=True)
        n = _copy_unique(paths, dest)
        return jsonify(ok=True, count=n, total=len(paths), dest=dest)

    # ----- series -----
    @app.get("/api/p/<slug>/series")
    def series_list(slug):
        _require(slug)
        c = _conn(slug)
        offset, limit = _page()
        total = c.execute("SELECT COUNT(*) FROM series WHERE frame_count>1").fetchone()[0]
        rows = c.execute(
            """SELECT s.id, s.frame_count, s.best_image_id,
                 (SELECT print_score FROM images WHERE id=s.best_image_id) best_score
               FROM series s WHERE s.frame_count>1
               ORDER BY s.frame_count DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        return _paged([dict(r) for r in rows], total, offset, limit)

    @app.get("/api/p/<slug>/series/<int:sid>/images")
    def series_images(slug, sid):
        _require(slug)
        c = _conn(slug)
        rows = c.execute(
            """SELECT id, path, print_score, is_best_in_series, global_sharpness, exposure_score,
                 EXISTS(SELECT 1 FROM picks WHERE image_id=images.id AND pick_type='print') AS is_print
               FROM images WHERE series_id=? ORDER BY print_score DESC""",
            (sid,),
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    # picks are image-anchored (survive series regroup); auto picks derived here.
    _SCORE_COL = {"group": "print_score", "aesthetic": "aesthetic_score", "candid": "candid_score"}

    @app.get("/api/p/<slug>/series/<int:sid>/picks")
    def series_picks(slug, sid):
        _require(slug)
        c = _conn(slug)
        imgs = list(
            c.execute(
                """SELECT id, print_score, aesthetic_score, candid_score
               FROM images WHERE series_id=?""",
                (sid,),
            )
        )
        if not imgs:
            return jsonify(pick_types=config.PICK_TYPES, picks=[])
        ids = [r["id"] for r in imgs]
        ph = ",".join("?" * len(ids))
        manual = {
            r["pick_type"]: r["image_id"]
            for r in c.execute(
                f"""SELECT pick_type, image_id FROM picks
                WHERE source='manual' AND image_id IN ({ph})""",
                ids,
            )
        }
        out = []
        for ptype in config.PICK_TYPES:
            if ptype in manual:
                out.append({"pick_type": ptype, "image_id": manual[ptype], "source": "manual"})
                continue
            col = _SCORE_COL[ptype]
            cand = [(r[col], r["id"]) for r in imgs if r[col] is not None]
            if cand:
                out.append({"pick_type": ptype, "image_id": max(cand)[1], "source": "auto"})
        return jsonify(pick_types=config.PICK_TYPES, picks=out)

    @app.post("/api/p/<slug>/series/<int:sid>/pick")
    def set_pick(slug, sid):
        _require(slug)
        body = request.json or {}
        ptype, iid = body.get("pick_type"), body.get("image_id")
        if ptype not in config.PICK_TYPES or iid is None:
            return jsonify(ok=False, msg="bad pick_type / image_id"), 400
        c = _conn(slug)
        ids = [r[0] for r in c.execute("SELECT id FROM images WHERE series_id=?", (sid,))]
        if iid not in ids:
            return jsonify(ok=False, msg="image not in series"), 400
        already = c.execute(
            "SELECT 1 FROM picks WHERE image_id=? AND pick_type=? AND source='manual'", (iid, ptype)
        ).fetchone()
        ph = ",".join("?" * len(ids))
        c.execute(f"DELETE FROM picks WHERE pick_type=? AND image_id IN ({ph})", [ptype, *ids])
        if not already:  # was already manual here -> the delete toggled it off
            c.execute(
                "INSERT INTO picks(image_id, pick_type, source, reason) VALUES(?,?,'manual','user')", (iid, ptype)
            )
        c.commit()
        return jsonify(ok=True)

    # ----- print list (starred keepers; multiple per burst allowed) -----
    @app.post("/api/p/<slug>/star/<int:iid>")
    def star(slug, iid):
        _require(slug)
        c = _conn(slug)
        existing = c.execute("SELECT 1 FROM picks WHERE image_id=? AND pick_type='print'", (iid,)).fetchone()
        if existing:
            c.execute("DELETE FROM picks WHERE image_id=? AND pick_type='print'", (iid,))
            starred = False
        else:
            c.execute(
                "INSERT OR IGNORE INTO picks(image_id, pick_type, source, reason) "
                "VALUES(?, 'print', 'manual', 'starred')",
                (iid,),
            )
            starred = True
        c.commit()
        return jsonify(ok=True, starred=starred)

    @app.post("/api/p/<slug>/star_many")
    def star_many(slug):
        _require(slug)
        ids = (request.json or {}).get("image_ids") or []
        c = _conn(slug)
        for iid in ids:
            c.execute(
                "INSERT OR IGNORE INTO picks(image_id, pick_type, source, reason) "
                "VALUES(?, 'print', 'manual', 'starred')",
                (int(iid),),
            )
        c.commit()
        starred = c.execute("SELECT COUNT(*) FROM picks WHERE pick_type='print'").fetchone()[0]
        return jsonify(ok=True, starred=starred)

    @app.get("/api/p/<slug>/prints")
    def prints(slug):
        _require(slug)
        c = _conn(slug)
        offset, limit = _page()
        total = c.execute("SELECT COUNT(*) FROM picks WHERE pick_type='print'").fetchone()[0]
        rows = c.execute(
            """SELECT i.id, i.path, i.series_id, i.print_score
               FROM picks p JOIN images i ON i.id=p.image_id
               WHERE p.pick_type='print' ORDER BY i.series_id, i.id LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        return _paged([dict(r) for r in rows], total, offset, limit)

    @app.post("/api/p/<slug>/prints/export")
    def export_prints(slug):
        _require(slug)
        dest = _safe_dest((request.json or {}).get("dest") or f"./print_exports/{slug}")
        if not dest:
            return jsonify(ok=False, msg="choose a valid destination folder"), 400
        rows = (
            _conn(slug)
            .execute("SELECT i.path FROM picks p JOIN images i ON i.id=p.image_id WHERE p.pick_type='print'")
            .fetchall()
        )
        os.makedirs(dest, exist_ok=True)
        n = _copy_unique([r["path"] for r in rows], dest)
        return jsonify(ok=True, count=n, dest=dest)

    # ----- face detail -----
    @app.get("/api/p/<slug>/face/<int:fid>")
    def face_detail(slug, fid):
        _require(slug)
        c = _conn(slug)
        r = c.execute(
            """SELECT f.*, i.path, i.width, i.height, p.display_name
               FROM faces f JOIN images i ON i.id=f.image_id
               LEFT JOIN persons p ON p.id=f.person_id WHERE f.id=?""",
            (fid,),
        ).fetchone()
        if not r:
            abort(404)
        d = dict(r)
        d.pop("embedding", None)
        d.pop("thumbnail", None)
        return jsonify(d)

    # ----- media -----
    @app.get("/api/p/<slug>/thumb/<int:fid>")
    def face_thumb(slug, fid):
        _require(slug)
        r = _conn(slug).execute("SELECT thumbnail FROM faces WHERE id=?", (fid,)).fetchone()
        if not r or not r["thumbnail"]:
            abort(404)
        resp = send_file(io.BytesIO(r["thumbnail"]), mimetype="image/jpeg")
        resp.headers["Cache-Control"] = "public, max-age=86400"  # immutable face crop; avoid refetch
        return resp

    @app.get("/api/p/<slug>/image_thumb/<int:iid>")
    def image_thumb(slug, iid):
        _require(slug)
        r = _conn(slug).execute("SELECT thumbnail, path FROM images WHERE id=?", (iid,)).fetchone()
        if not r:
            abort(404)
        if r["thumbnail"]:  # fast path: precomputed thumbnail
            resp = send_file(io.BytesIO(r["thumbnail"]), mimetype="image/jpeg")
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp
        if not os.path.exists(r["path"]):  # fallback: decode original (pre-v2 rows)
            abort(404)
        from PIL import Image

        im = Image.open(r["path"])
        im.draft("RGB", (640, 640))
        im = im.convert("RGB")
        im.thumbnail((480, 480))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        buf.seek(0)
        resp = send_file(buf, mimetype="image/jpeg")
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.get("/api/p/<slug>/image/<int:iid>")
    def full_image(slug, iid):
        _require(slug)
        r = _conn(slug).execute("SELECT path FROM images WHERE id=?", (iid,)).fetchone()
        if not r or not os.path.exists(r["path"]):
            abort(404)
        return send_file(r["path"])

    @app.post("/api/p/<slug>/export/<int:iid>")
    def export(slug, iid):
        _require(slug)
        dest = _safe_dest((request.json or {}).get("dest") or "./print_exports")
        if not dest:
            return jsonify(ok=False, msg="choose a valid destination folder"), 400
        r = _conn(slug).execute("SELECT path FROM images WHERE id=?", (iid,)).fetchone()
        if not r or not os.path.exists(r["path"]):
            abort(404)
        os.makedirs(dest, exist_ok=True)
        out = os.path.join(dest, os.path.basename(r["path"]))
        shutil.copy2(r["path"], out)
        return jsonify(ok=True, path=out)

    # ----- JSON error handling (no raw HTML 500s) -----
    @app.errorhandler(sqlite3.Error)
    def handle_sqlite_error(e):
        return jsonify(ok=False, error=str(e)), 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        if isinstance(e, HTTPException):
            return e
        return jsonify(ok=False, error=str(e)), 500

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects-dir", default=None)
    ap.add_argument("--port", type=int, default=5050)
    args = ap.parse_args()
    args.projects_dir = args.projects_dir or config.default_projects_dir()
    print(f"http://localhost:{args.port}  (projects: {os.path.abspath(args.projects_dir)})")
    # Loopback only and unauthenticated by design — never expose beyond 127.0.0.1.
    create_app(args.projects_dir).run(host="127.0.0.1", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
