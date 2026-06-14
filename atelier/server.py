#!/usr/bin/env python3
"""Phase 4 — Browse. Project-centric Flask REST API + static SPA.

Each project owns its own SQLite DB (see atelier.projects). The dashboard
creates projects, a native macOS dialog picks the source folder, the pipeline
runs in the background with a live console, and People/Series/Faces are browsed
per project.
"""
import argparse
import io
import os
import shutil
import sqlite3

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

from atelier import config, db, fsdialog, migrate, overrides, projects, settings
from atelier.runner import get_runner

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def create_app(projects_dir):
    app = Flask(__name__, static_folder=None)
    os.makedirs(projects_dir, exist_ok=True)
    # one-time migration: flat ./projects -> nested ~/.atelier on first launch
    if not os.path.exists(os.path.join(projects_dir, "registry.json")):
        n = migrate.migrate_flat_to_nested("projects", projects_dir)
        if n:
            print(f"migrated {n} project(s) from ./projects -> {projects_dir}")

    # ----- helpers -----
    def _require(slug):
        proj = projects.get_project(projects_dir, slug)
        if not proj:
            abort(404, description=f"no project '{slug}'")
        return proj

    def _conn(slug):
        return db.connect(projects.db_path(projects_dir, slug))

    def _runner(slug):
        return get_runner(slug, projects.db_path(projects_dir, slug),
                          projects.log_path(projects_dir, slug))

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
        return send_from_directory(WEB_DIR, "index.html")

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
            return jsonify(ok=False, msg="cancelled or unavailable"), 200
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
                item["cover"] = [r[0] for r in c.execute(
                    """SELECT id FROM images WHERE processed=1 AND thumbnail IS NOT NULL
                       ORDER BY print_score DESC LIMIT 5""")]
                if not item["cover"]:
                    item["cover"] = [r[0] for r in c.execute(
                        "SELECT id FROM images WHERE processed=1 LIMIT 5")]
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
        phases = settings.PHASES_FOR.get(body.get("affects"))   # None -> full pipeline
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
        total = c.execute(
            f"SELECT COUNT(*) FROM persons p {where}", params).fetchone()[0]
        rows = c.execute(
            f"""SELECT p.id, p.display_name, COUNT(f.id) cnt,
                 (SELECT id FROM faces WHERE person_id=p.id
                  ORDER BY is_best DESC, quality_score DESC LIMIT 1) best_face
               FROM persons p LEFT JOIN faces f ON f.person_id=p.id
               {where}
               GROUP BY p.id ORDER BY cnt DESC LIMIT ? OFFSET ?""",
            (*params, limit, offset)).fetchall()
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
               LIMIT ? OFFSET ?""", (pid, limit, offset)).fetchall()
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
               ORDER BY s.frame_count DESC LIMIT ? OFFSET ?""", (limit, offset)).fetchall()
        return _paged([dict(r) for r in rows], total, offset, limit)

    @app.get("/api/p/<slug>/series/<int:sid>/images")
    def series_images(slug, sid):
        _require(slug)
        c = _conn(slug)
        rows = c.execute(
            """SELECT id, path, print_score, is_best_in_series, global_sharpness, exposure_score,
                 EXISTS(SELECT 1 FROM picks WHERE image_id=images.id AND pick_type='print') AS is_print
               FROM images WHERE series_id=? ORDER BY print_score DESC""", (sid,)).fetchall()
        return jsonify([dict(r) for r in rows])

    # picks are image-anchored (survive series regroup); auto picks derived here.
    _SCORE_COL = {"group": "print_score", "aesthetic": "aesthetic_score", "candid": "candid_score"}

    @app.get("/api/p/<slug>/series/<int:sid>/picks")
    def series_picks(slug, sid):
        _require(slug)
        c = _conn(slug)
        imgs = list(c.execute(
            """SELECT id, print_score, aesthetic_score, candid_score
               FROM images WHERE series_id=?""", (sid,)))
        if not imgs:
            return jsonify(pick_types=config.PICK_TYPES, picks=[])
        ids = [r["id"] for r in imgs]
        ph = ",".join("?" * len(ids))
        manual = {r["pick_type"]: r["image_id"] for r in c.execute(
            f"""SELECT pick_type, image_id FROM picks
                WHERE source='manual' AND image_id IN ({ph})""", ids)}
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
            "SELECT 1 FROM picks WHERE image_id=? AND pick_type=? AND source='manual'",
            (iid, ptype)).fetchone()
        ph = ",".join("?" * len(ids))
        c.execute(f"DELETE FROM picks WHERE pick_type=? AND image_id IN ({ph})", [ptype, *ids])
        if not already:   # was already manual here -> the delete toggled it off
            c.execute("INSERT INTO picks(image_id, pick_type, source, reason) VALUES(?,?,'manual','user')",
                      (iid, ptype))
        c.commit()
        return jsonify(ok=True)

    # ----- print list (starred keepers; multiple per burst allowed) -----
    @app.post("/api/p/<slug>/star/<int:iid>")
    def star(slug, iid):
        _require(slug)
        c = _conn(slug)
        existing = c.execute(
            "SELECT 1 FROM picks WHERE image_id=? AND pick_type='print'", (iid,)).fetchone()
        if existing:
            c.execute("DELETE FROM picks WHERE image_id=? AND pick_type='print'", (iid,))
            starred = False
        else:
            c.execute("INSERT OR IGNORE INTO picks(image_id, pick_type, source, reason) "
                      "VALUES(?, 'print', 'manual', 'starred')", (iid,))
            starred = True
        c.commit()
        return jsonify(ok=True, starred=starred)

    @app.post("/api/p/<slug>/star_many")
    def star_many(slug):
        _require(slug)
        ids = (request.json or {}).get("image_ids") or []
        c = _conn(slug)
        for iid in ids:
            c.execute("INSERT OR IGNORE INTO picks(image_id, pick_type, source, reason) "
                      "VALUES(?, 'print', 'manual', 'starred')", (int(iid),))
        c.commit()
        starred = c.execute("SELECT COUNT(*) FROM picks WHERE pick_type='print'").fetchone()[0]
        return jsonify(ok=True, starred=starred)

    @app.get("/api/p/<slug>/prints")
    def prints(slug):
        _require(slug)
        rows = _conn(slug).execute(
            """SELECT i.id, i.path, i.series_id, i.print_score
               FROM picks p JOIN images i ON i.id=p.image_id
               WHERE p.pick_type='print' ORDER BY i.series_id, i.id""").fetchall()
        return jsonify([dict(r) for r in rows])

    @app.post("/api/p/<slug>/prints/export")
    def export_prints(slug):
        _require(slug)
        dest = (request.json or {}).get("dest", f"./print_exports/{slug}")
        rows = _conn(slug).execute(
            "SELECT i.path FROM picks p JOIN images i ON i.id=p.image_id WHERE p.pick_type='print'"
        ).fetchall()
        os.makedirs(dest, exist_ok=True)
        n = 0
        for r in rows:
            if os.path.exists(r["path"]):
                shutil.copy2(r["path"], os.path.join(dest, os.path.basename(r["path"])))
                n += 1
        return jsonify(ok=True, count=n, dest=os.path.abspath(dest))

    # ----- face detail -----
    @app.get("/api/p/<slug>/face/<int:fid>")
    def face_detail(slug, fid):
        _require(slug)
        c = _conn(slug)
        r = c.execute(
            """SELECT f.*, i.path, i.width, i.height, p.display_name
               FROM faces f JOIN images i ON i.id=f.image_id
               LEFT JOIN persons p ON p.id=f.person_id WHERE f.id=?""", (fid,)).fetchone()
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
        return send_file(io.BytesIO(r["thumbnail"]), mimetype="image/jpeg")

    @app.get("/api/p/<slug>/image_thumb/<int:iid>")
    def image_thumb(slug, iid):
        _require(slug)
        r = _conn(slug).execute("SELECT thumbnail, path FROM images WHERE id=?", (iid,)).fetchone()
        if not r:
            abort(404)
        if r["thumbnail"]:                       # fast path: precomputed thumbnail
            resp = send_file(io.BytesIO(r["thumbnail"]), mimetype="image/jpeg")
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp
        if not os.path.exists(r["path"]):        # fallback: decode original (pre-v2 rows)
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
        dest = (request.json or {}).get("dest", "./print_exports")
        r = _conn(slug).execute("SELECT path FROM images WHERE id=?", (iid,)).fetchone()
        if not r or not os.path.exists(r["path"]):
            abort(404)
        os.makedirs(dest, exist_ok=True)
        out = os.path.join(dest, os.path.basename(r["path"]))
        shutil.copy2(r["path"], out)
        return jsonify(ok=True, path=os.path.abspath(out))

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
    create_app(args.projects_dir).run(port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
