"""Manual identity overrides (merge / split / reassign) that survive re-clustering.

Anchored on faces.id — the only key stable across re-runs (persons.id is the raw
HDBSCAN label and is rebuilt every clustering pass). A `group_key` denotes one
forced identity. apply_overrides() re-imposes that intent after HDBSCAN runs.
"""
import time
import uuid


def new_group_key():
    return uuid.uuid4().hex


def _face_ids_of_person(conn, pid):
    return [r[0] for r in conn.execute("SELECT id FROM faces WHERE person_id=?", (pid,))]


def _group_keys_of_person(conn, pid):
    return [r[0] for r in conn.execute(
        """SELECT DISTINCT o.group_key FROM person_overrides o
           JOIN faces f ON f.id=o.face_id WHERE f.person_id=?""", (pid,))]


def _write_rows(conn, face_ids, group_key, kind, name):
    now = time.time()
    conn.executemany(
        """INSERT INTO person_overrides(face_id, group_key, kind, display_name, created_at)
           VALUES(?,?,?,?,?)
           ON CONFLICT(face_id) DO UPDATE SET group_key=excluded.group_key,
             kind=excluded.kind, display_name=excluded.display_name""",
        [(fid, group_key, kind, name, now) for fid in face_ids])


def merge_persons(conn, from_pid, into_pid, name=None):
    """Force every face of both persons into one identity. Survives re-clustering."""
    faces = _face_ids_of_person(conn, from_pid) + _face_ids_of_person(conn, into_pid)
    if not faces:
        return None
    existing = _group_keys_of_person(conn, into_pid)
    gk = existing[0] if existing else new_group_key()
    if name is None:
        row = conn.execute("SELECT display_name FROM persons WHERE id=?", (into_pid,)).fetchone()
        name = row["display_name"] if row else None
    _write_rows(conn, faces, gk, "merge", name)
    conn.execute("UPDATE faces SET person_id=? WHERE person_id=?", (into_pid, from_pid))
    conn.execute("DELETE FROM persons WHERE id=?", (from_pid,))
    conn.commit()
    return gk


def reassign_face(conn, face_id, into_pid):
    """Move one face into a person (merge semantics — joins that person's group)."""
    existing = _group_keys_of_person(conn, into_pid)
    gk = existing[0] if existing else new_group_key()
    name_row = conn.execute("SELECT display_name FROM persons WHERE id=?", (into_pid,)).fetchone()
    name = name_row["display_name"] if name_row else None
    if not existing:
        # seed the group with the target person's current faces so the identity is stable
        _write_rows(conn, _face_ids_of_person(conn, into_pid), gk, "merge", name)
    _write_rows(conn, [face_id], gk, "reassign", name)
    conn.execute("UPDATE faces SET person_id=? WHERE id=?", (into_pid, face_id))
    conn.commit()
    return gk


def split_person(conn, face_ids, name=None):
    """Peel faces out of a cluster into a new, separate identity."""
    if not face_ids:
        return None
    gk = new_group_key()
    _write_rows(conn, face_ids, gk, "split", name)
    nid = (conn.execute("SELECT COALESCE(MAX(id), -1) FROM persons").fetchone()[0]) + 1
    conn.execute("INSERT OR IGNORE INTO persons(id, display_name) VALUES(?,?)",
                 (nid, name or f"Person {nid}"))
    placeholders = ",".join("?" * len(face_ids))
    conn.execute(f"UPDATE faces SET person_id=? WHERE id IN ({placeholders})", [nid, *face_ids])
    conn.commit()
    return gk


def set_group_name(conn, person_id, name):
    """Persist a rename so it survives re-clustering: update the person AND any
    override group(s) covering its faces."""
    conn.execute("UPDATE persons SET display_name=? WHERE id=?", (name, person_id))
    for gk in _group_keys_of_person(conn, person_id):
        conn.execute("UPDATE person_overrides SET display_name=? WHERE group_key=?", (name, gk))
    conn.commit()


def apply_overrides(conn):
    """Re-impose all manual overrides after HDBSCAN has assigned fresh person_ids.
    Call at the end of clustering. Idempotent."""
    groups = {}  # group_key -> {faces:[], name, kind}
    for r in conn.execute("SELECT face_id, group_key, kind, display_name FROM person_overrides"):
        g = groups.setdefault(r["group_key"], {"faces": [], "name": None, "kind": r["kind"]})
        g["faces"].append(r["face_id"])
        if r["display_name"]:
            g["name"] = r["display_name"]
        if r["kind"] == "split":
            g["kind"] = "split"
    if not groups:
        return

    next_id = (conn.execute("SELECT COALESCE(MAX(id), -1) FROM persons").fetchone()[0]) + 1
    used_targets = set()
    for gk, g in groups.items():
        fids = g["faces"]
        ph = ",".join("?" * len(fids))
        target = None
        if g["kind"] != "split":
            row = conn.execute(
                f"""SELECT person_id, COUNT(*) c FROM faces
                    WHERE id IN ({ph}) AND person_id>=0
                    GROUP BY person_id ORDER BY c DESC LIMIT 1""", fids).fetchone()
            if row and row["person_id"] not in used_targets:
                target = row["person_id"]
        if target is None:
            target = next_id
            next_id += 1
        used_targets.add(target)
        conn.execute(f"UPDATE faces SET person_id=? WHERE id IN ({ph})", [target, *fids])
        conn.execute("INSERT OR IGNORE INTO persons(id, display_name) VALUES(?,?)",
                     (target, g["name"] or f"Person {target}"))
        if g["name"]:
            conn.execute("UPDATE persons SET display_name=? WHERE id=?", (g["name"], target))
    conn.commit()
