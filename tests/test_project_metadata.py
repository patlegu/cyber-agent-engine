import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _proj() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_license_is_agpl_spdx():
    assert _proj()["license"] == "AGPL-3.0-or-later"


def test_authors_present():
    authors = _proj()["authors"]
    assert authors and authors[0]["name"] and "@" in authors[0]["email"]


def test_urls_present():
    urls = _proj()["urls"]
    for key in ("Homepage", "Repository", "Issues"):
        assert key in urls and urls[key].startswith("https://")


def test_classifiers_include_agpl_and_security():
    proj = _proj()
    joined = " ".join(proj["classifiers"])
    license_text = proj.get("license", "")
    assert ("Affero" in joined or "AGPL" in license_text) and "Topic :: Security" in joined


def test_description_is_current_not_factory():
    desc = _proj()["description"].lower()
    assert "factory" not in desc
    assert "coordinator" in desc or "security" in desc
