import os

import pytest

from atelier import projects


def test_slugify_basic_and_unique():
    assert projects.slugify("Wedding 2024", set()) == "wedding-2024"
    assert projects.slugify("Wedding 2024!!", {"wedding-2024"}) == "wedding-2024-2"
    assert projects.slugify("", set()) == "project"


def test_create_list_get_delete(tmp_path):
    pdir = str(tmp_path / "projects")
    src = tmp_path / "photos"
    src.mkdir()

    proj = projects.create_project(pdir, "My Wedding", str(src), now=1000.0)
    assert proj["slug"] == "my-wedding"
    assert proj["created_at"] == 1000.0
    assert os.path.exists(projects.db_path(pdir, "my-wedding"))  # DB materialized

    assert len(projects.list_projects(pdir)) == 1
    assert projects.get_project(pdir, "my-wedding")["name"] == "My Wedding"

    projects.delete_project(pdir, "my-wedding")
    assert projects.get_project(pdir, "my-wedding") is None
    assert not os.path.exists(projects.db_path(pdir, "my-wedding"))


def test_create_rejects_bad_input(tmp_path):
    pdir = str(tmp_path / "projects")
    with pytest.raises(ValueError):
        projects.create_project(pdir, "", str(tmp_path))
    with pytest.raises(ValueError):
        projects.create_project(pdir, "X", str(tmp_path / "nope"))


def test_duplicate_names_get_unique_slugs(tmp_path):
    pdir = str(tmp_path / "projects")
    src = tmp_path / "p"
    src.mkdir()
    a = projects.create_project(pdir, "Trip", str(src), now=1.0)
    b = projects.create_project(pdir, "Trip", str(src), now=2.0)
    assert a["slug"] != b["slug"]
    assert {a["slug"], b["slug"]} == {"trip", "trip-2"}


def test_stats_empty_then_counts(tmp_path):
    pdir = str(tmp_path / "projects")
    src = tmp_path / "p"
    src.mkdir()
    projects.create_project(pdir, "S", str(src), now=1.0)
    st = projects.stats(pdir, "s")
    assert st == {"images": 0, "faces": 0, "persons": 0, "series": 0}


def test_register_existing(tmp_path):
    pdir = str(tmp_path / "projects")
    src = tmp_path / "p"
    src.mkdir()
    proj = projects.register_existing(pdir, "Demo", str(src), now=5.0)
    assert proj["slug"] == "demo"
    assert projects.get_project(pdir, "demo")["source_folder"] == os.path.abspath(str(src))
