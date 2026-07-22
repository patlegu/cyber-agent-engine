from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_both_readmes_exist():
    assert (_ROOT / "README.md").exists()
    assert (_ROOT / "README.fr.md").exists()


def test_cross_links():
    en = (_ROOT / "README.md").read_text(encoding="utf-8")
    fr = (_ROOT / "README.fr.md").read_text(encoding="utf-8")
    assert "README.fr.md" in en   # EN pointe vers FR
    assert "README.md" in fr      # FR pointe vers EN


def test_english_readme_markers():
    en = (_ROOT / "README.md").read_text(encoding="utf-8")
    # sections clés en anglais
    assert "Docker deployment" in en
    assert "License" in en and "AGPL" in en
    # pas de titre de section resté en français
    assert "## Démarrage" not in en


def test_french_readme_keeps_french_and_license():
    fr = (_ROOT / "README.fr.md").read_text(encoding="utf-8")
    assert "Licence" in fr and "AGPL" in fr
