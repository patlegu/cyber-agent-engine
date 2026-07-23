"""Garde-fou : la surface ruff des workflows CI reste alignée sur `[tool.mypy].files`.

La liste des chemins « surface source maintenue » apparaît à trois endroits
(`ci.yml`, `release.yml`, `pyproject.toml`). Ce test échoue si l'un d'eux dérive,
transformant tout drop silencieux de chemin en test rouge.
"""

import tomllib
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent


def _mypy_files() -> set[str]:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return set(data["tool"]["mypy"]["files"])


def _ruff_surface(workflow: str) -> set[str]:
    wf = yaml.safe_load((_ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8"))
    run = next(
        step["run"] for step in wf["jobs"]["test"]["steps"] if "ruff check" in step.get("run", "")
    )
    tokens = run.split()
    assert tokens[:2] == ["ruff", "check"]  # sanity : bien la commande ruff
    return set(tokens[2:])


def test_ci_ruff_surface_matches_mypy_files():
    assert _ruff_surface("ci.yml") == _mypy_files()


def test_release_ruff_surface_matches_mypy_files():
    assert _ruff_surface("release.yml") == _mypy_files()
