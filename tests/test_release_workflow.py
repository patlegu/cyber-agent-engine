from pathlib import Path
import yaml

_ROOT = Path(__file__).resolve().parent.parent


def _wf() -> dict:
    return yaml.safe_load((_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))


def _on(wf: dict):
    return wf.get(True, wf.get("on"))


def test_triggers_on_version_tags():
    tags = _on(_wf())["push"]["tags"]
    assert any(t.startswith("v") for t in tags)


def test_publish_jobs_need_test():
    jobs = _wf()["jobs"]
    assert "test" in jobs and "publish-pypi" in jobs and "publish-ghcr" in jobs
    assert "test" in jobs["publish-pypi"]["needs"]
    assert "test" in jobs["publish-ghcr"]["needs"]


def test_pypi_uses_oidc_no_token():
    pypi = _wf()["jobs"]["publish-pypi"]
    assert pypi["permissions"]["id-token"] == "write"    # OIDC
    text = yaml.dump(pypi)
    assert "gh-action-pypi-publish" in text
    assert "PYPI_API_TOKEN" not in text                   # pas de secret token
    assert "python -m build" in text


def test_ghcr_pushes_version_and_latest():
    ghcr = _wf()["jobs"]["publish-ghcr"]
    assert ghcr["permissions"]["packages"] == "write"
    text = yaml.dump(ghcr)
    assert "ghcr.io" in text
    assert "GITHUB_TOKEN" in text
    assert ":latest" in text and "ref_name" in text        # version depuis le tag + latest


def test_version_consistency_check_present():
    text = yaml.dump(_wf())
    # un check échoue si le tag != [project].version
    assert "version" in text and ("pyproject" in text or "project" in text)
