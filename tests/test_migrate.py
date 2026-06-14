import os

from atelier import config, db, migrate, projects


def test_default_projects_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ATELIER_HOME", str(tmp_path / "home"))
    assert config.default_projects_dir() == str(tmp_path / "home")
    monkeypatch.delenv("ATELIER_HOME")
    assert config.default_projects_dir().endswith(".atelier")


def test_nested_paths(tmp_path):
    root = str(tmp_path / "atelier")
    assert projects.db_path(root, "wedding") == os.path.join(root, "wedding", "db.sqlite")
    assert projects.log_path(root, "wedding") == os.path.join(root, "wedding", "run.log")


def test_create_uses_nested_dir(tmp_path):
    root = str(tmp_path / "atelier")
    src = tmp_path / "photos"
    src.mkdir()
    projects.create_project(root, "Wedding", str(src), now=1.0)
    assert os.path.isdir(os.path.join(root, "wedding"))
    assert os.path.exists(os.path.join(root, "wedding", "db.sqlite"))


def test_migrate_flat_to_nested(tmp_path):
    # build an old flat layout
    src = tmp_path / "projects"
    src.mkdir()
    db.init_db(str(src / "wed.db")).close()
    (src / "registry.json").write_text(
        '[{"slug":"wed","name":"Wed","source_folder":"/x","created_at":1.0}]')
    (src / "wed.log").write_text("old log\n")

    dst = str(tmp_path / "atelier")
    n = migrate.migrate_flat_to_nested(str(src), dst)
    assert n == 1
    assert os.path.exists(os.path.join(dst, "registry.json"))
    assert os.path.exists(os.path.join(dst, "wed", "db.sqlite"))
    assert os.path.exists(os.path.join(dst, "wed", "run.log"))
    # idempotent
    assert migrate.migrate_flat_to_nested(str(src), dst) == 0
