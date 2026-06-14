import os
import tempfile

from PIL import Image

from facelib import imaging


def test_png_falls_back_to_mtime():
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        Image.new("RGB", (8, 8), (120, 120, 120)).save(path)
        img = imaging.load_rgb(path)
        taken_at, exif_time, sub_sec, camera, orient = imaging.read_metadata(path, img)
        assert exif_time is False          # PNG has no EXIF DateTimeOriginal
        assert taken_at is not None        # mtime fallback always set
        assert abs(taken_at - os.path.getmtime(path)) < 1.0
    finally:
        os.remove(path)


def test_load_rgb_applies_exif_orientation():
    # a portrait stored as landscape + EXIF orientation must come back upright
    fd, path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    try:
        portrait = Image.new("RGB", (60, 90), (128, 64, 32))
        landscape = portrait.rotate(-90, expand=True)   # 90x60, content rotated
        ex = landscape.getexif()
        ex[274] = 8                                       # orientation: rotate back
        landscape.save(path, exif=ex)
        loaded = imaging.load_rgb(path)
        assert loaded.size == (60, 90)                    # restored to upright portrait
    finally:
        os.remove(path)


def test_analysis_resize_caps_long_edge():
    img = Image.new("RGB", (4000, 2000))
    small, scale = imaging.analysis_resize(img, 1536)
    assert max(small.size) == 1536
    assert scale < 1.0


def test_analysis_resize_no_upscale():
    img = Image.new("RGB", (800, 600))
    same, scale = imaging.analysis_resize(img, 1536)
    assert same.size == (800, 600)
    assert scale == 1.0


def test_iter_images_filters_extensions(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "b.png").write_bytes(b"x")
    (tmp_path / "c.txt").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.jpeg").write_bytes(b"x")
    found = {p.name for p in imaging.iter_images(tmp_path)}
    assert found == {"a.jpg", "b.png", "d.jpeg"}
