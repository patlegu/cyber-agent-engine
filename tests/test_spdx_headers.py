# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SPDX = "SPDX-License-Identifier: AGPL-3.0-or-later"
_DIRS = ("core", "coordinator", "agents", "clients")
_ROOT_FILES = ("server.py",)


def _first_party_sources() -> list[Path]:
    files: list[Path] = []
    for d in _DIRS:
        files.extend((_ROOT / d).rglob("*.py"))
    files.extend(_ROOT / f for f in _ROOT_FILES)
    return files


def test_every_first_party_source_has_spdx_header():
    missing = []
    for f in _first_party_sources():
        head = "\n".join(f.read_text(encoding="utf-8").splitlines()[:3])
        if _SPDX not in head:
            missing.append(str(f.relative_to(_ROOT)))
    assert not missing, f"fichiers sans en-tête SPDX: {missing}"


def test_scope_excludes_tests_and_dashboard():
    paths = {str(f.relative_to(_ROOT)) for f in _first_party_sources()}
    assert not any(p.startswith("tests/") or p.startswith("dashboard/") for p in paths)
