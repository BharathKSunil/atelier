from atelier import db, overrides


def _seed(path):
    c = db.init_db(path)
    c.execute("INSERT INTO images(id, path, processed) VALUES(1, '/a.jpg', 1)")
    for fid, pid in [(1, 0), (2, 0), (3, 1), (4, 1)]:
        c.execute("INSERT INTO faces(id, image_id, person_id) VALUES(?,?,?)", (fid, 1, pid))
    c.execute("INSERT INTO persons(id, display_name) VALUES(0, 'Alice')")
    c.execute("INSERT INTO persons(id, display_name) VALUES(1, 'Bob')")
    c.commit()
    return c


def test_merge_survives_recluster(tmp_path):
    c = _seed(str(tmp_path / "m.db"))
    overrides.merge_persons(c, 1, 0)  # merge Bob into Alice
    assert {r[0] for r in c.execute("SELECT DISTINCT person_id FROM faces")} == {0}
    # simulate a re-cluster scattering the faces, then re-apply intent
    c.execute("UPDATE faces SET person_id=7 WHERE id IN (1,2)")
    c.execute("UPDATE faces SET person_id=9 WHERE id IN (3,4)")
    overrides.apply_overrides(c)
    assert len({r[0] for r in c.execute("SELECT person_id FROM faces")}) == 1


def test_chained_merge_keeps_orphaned_faces_together(tmp_path):
    """A face that drifted to noise between two merges must not re-materialize a
    separate person on re-cluster (the merge_persons orphan-group bug)."""
    c = _seed(str(tmp_path / "c.db"))
    c.execute("INSERT INTO persons(id, display_name) VALUES(2, 'Carol')")
    for fid in (5, 6):
        c.execute("INSERT INTO faces(id, image_id, person_id) VALUES(?,1,2)", (fid,))
    c.commit()
    overrides.merge_persons(c, 1, 0)  # Bob -> Alice (group covers 1,2,3,4)
    c.execute("UPDATE faces SET person_id=-1 WHERE id=4")  # face 4 drifts to noise
    overrides.merge_persons(c, 0, 2)  # Alice -> Carol; face 4 would orphan
    # simulate a re-cluster scattering everyone, then re-apply intent
    c.execute("UPDATE faces SET person_id=10 WHERE id IN (1,2,3)")
    c.execute("UPDATE faces SET person_id=11 WHERE id IN (5,6)")
    c.execute("UPDATE faces SET person_id=12 WHERE id=4")
    overrides.apply_overrides(c)
    groups = {r[0] for r in c.execute("SELECT person_id FROM faces WHERE id IN (1,2,3,4,5,6)")}
    assert len(groups) == 1


def test_split_survives_recluster(tmp_path):
    c = _seed(str(tmp_path / "s.db"))
    overrides.split_person(c, [3, 4], name="Carol")
    new_pid = c.execute("SELECT person_id FROM faces WHERE id=3").fetchone()[0]
    assert new_pid not in (0, 1)
    # re-cluster lumps everyone together; split must peel 3,4 back out
    c.execute("UPDATE faces SET person_id=0")
    overrides.apply_overrides(c)
    p1 = c.execute("SELECT person_id FROM faces WHERE id=1").fetchone()[0]
    p3 = c.execute("SELECT person_id FROM faces WHERE id=3").fetchone()[0]
    assert p1 != p3


def test_rename_propagates_to_group(tmp_path):
    c = _seed(str(tmp_path / "r.db"))
    overrides.merge_persons(c, 1, 0)
    overrides.set_group_name(c, 0, "The Smiths")
    # name stored on the override group -> survives re-apply
    c.execute("UPDATE faces SET person_id=5")
    c.execute("DELETE FROM persons")
    overrides.apply_overrides(c)
    names = {r[0] for r in c.execute("SELECT display_name FROM persons")}
    assert "The Smiths" in names
