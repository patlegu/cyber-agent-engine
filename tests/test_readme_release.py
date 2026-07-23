from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_english_readme_documents_releases():
    en = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Trusted Publisher" in en          # setup PyPI OIDC
    assert "ghcr.io" in en                     # image GHCR
    assert "git tag v" in en                   # comment couper une release


def test_french_readme_documents_releases():
    fr = (_ROOT / "README.fr.md").read_text(encoding="utf-8")
    assert "Trusted Publisher" in fr
    assert "ghcr.io" in fr
    assert "git tag v" in fr
