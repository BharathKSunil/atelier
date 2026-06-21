"""Integration: the score phase stores P1 face signals (blendshape blink/gaze/Duchenne
+ head-pose Euler) and the gaze_frac tag, with graceful fallback. MediaPipe itself is
monkeypatched out so this runs without the model/runtime."""

import io

import numpy as np
from PIL import Image

from atelier import db, landmarks
from atelier.pipeline import score


def _jpeg():
    b = io.BytesIO()
    Image.new("RGB", (32, 32), (120, 120, 120)).save(b, "JPEG")
    return b.getvalue()


def _seed(path, thumb=True):
    conn = db.connect(path)
    conn.execute(
        """INSERT INTO images(id, path, processed, width, height, global_sharpness_raw, exposure_score)
           VALUES(1, '/a.jpg', 1, 1000, 800, 300, 0.8)"""
    )
    conn.execute(
        """INSERT INTO faces(id, image_id, face_index, thumbnail, face_sharpness, bbox_x1, bbox_y1, bbox_x2, bbox_y2)
           VALUES(1, 1, 0, ?, 0.7, 100, 100, 300, 300)""",
        (_jpeg() if thumb else None,),
    )
    conn.commit()
    conn.close()


def _run(path, monkeypatch, signals):
    monkeypatch.setattr(landmarks, "get_landmarker", lambda: object())  # have_mesh = True
    monkeypatch.setattr(landmarks, "face_signals", lambda arr: signals)
    monkeypatch.setattr("sys.argv", ["score", "--db", path])
    score.main()


def test_score_stores_p1_signals(tmp_path, monkeypatch):
    p = str(tmp_path / "f.db")
    _seed(p)
    # both eyes open, identity pose (frontal), eyes on the lens, genuine smile
    blend = {
        "eyeBlinkLeft": 0.0, "eyeBlinkRight": 0.0,
        "mouthSmileLeft": 0.8, "mouthSmileRight": 0.8, "cheekSquintLeft": 0.7, "cheekSquintRight": 0.7,
        "eyeLookInLeft": 0.0, "eyeLookOutLeft": 0.0, "eyeLookUpLeft": 0.0, "eyeLookDownLeft": 0.0,
        "eyeLookInRight": 0.0, "eyeLookOutRight": 0.0, "eyeLookUpRight": 0.0, "eyeLookDownRight": 0.0,
    }  # fmt: skip
    _run(p, monkeypatch, {"pts": np.zeros((478, 2)), "blend": blend, "matrix": np.eye(4)})

    conn = db.connect(p)
    f = conn.execute(
        "SELECT eye_open, eye_left, eye_right, yaw, gaze, genuine_smile, frontality FROM faces WHERE id=1"
    ).fetchone()
    assert f["eye_left"] == 1.0 and f["eye_right"] == 1.0
    assert f["gaze"] == 1.0  # looking at the lens
    assert f["genuine_smile"] > 0.7  # mouth + cheek co-activation
    assert f["frontality"] == 1.0  # identity transform -> frontal
    assert abs(f["yaw"]) < 1e-6
    im = conn.execute("SELECT gaze_frac, eyes_open_frac FROM images WHERE id=1").fetchone()
    assert im["gaze_frac"] == 1.0  # the one face makes eye contact
    assert im["eyes_open_frac"] == 1.0
    conn.close()


def test_score_falls_back_without_blendshapes(tmp_path, monkeypatch):
    """No blend dict / no matrix -> P1 columns stay null, gaze_frac null, but the
    legacy EAR/geometry path still scores eye_open/frontality/smile."""
    p = str(tmp_path / "f.db")
    _seed(p)
    pts = np.zeros((478, 2))  # degenerate mesh; geometry returns finite values
    _run(p, monkeypatch, {"pts": pts, "blend": {}, "matrix": None})

    conn = db.connect(p)
    f = conn.execute("SELECT eye_left, yaw, gaze, genuine_smile, eye_open, frontality FROM faces WHERE id=1").fetchone()
    assert f["eye_left"] is None and f["yaw"] is None and f["gaze"] is None and f["genuine_smile"] is None
    assert f["eye_open"] is not None and f["frontality"] is not None  # fallback path still ran
    im = conn.execute("SELECT gaze_frac FROM images WHERE id=1").fetchone()
    assert im["gaze_frac"] is None  # no gaze data -> no tag
    conn.close()
