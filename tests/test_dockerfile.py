# tests/test_dockerfile.py
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_present_slim_multistage_nonroot():
    df = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.11-slim" in df
    assert "as builder" in df.lower()          # multi-stage
    assert "USER appuser" in df                 # non-root
    # aucun secret en dur : pas de ENV *_KEY=<valeur>
    assert not re.search(r'ENV\s+\w*(KEY|SECRET|TOKEN)\w*\s*=\s*\S+', df)


def test_dockerignore_excludes_heavy_paths():
    di = (_ROOT / ".dockerignore").read_text(encoding="utf-8")
    for path in (".venv", "tests", ".git", "dist"):
        assert path in di
