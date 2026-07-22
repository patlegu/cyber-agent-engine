from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_MIN_LICENSE_LINES = 600


def test_license_file_present_and_agpl():
    text = (_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text
    assert "Version 3" in text
    # le texte canonique de l'AGPL fait ~660 lignes
    assert len(text.splitlines()) > _MIN_LICENSE_LINES
