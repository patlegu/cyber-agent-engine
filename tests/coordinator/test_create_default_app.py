import subprocess
import sys
from pathlib import Path

import pytest

from coordinator.app import create_default_app
from core.auth.api_key import AuthNotConfigured


def test_create_default_app_refuses_without_secrets(monkeypatch):
    monkeypatch.delenv("COORDINATOR_API_KEY", raising=False)
    # l'auth secret est requis pour construire l'app (fail-closed)
    with pytest.raises(AuthNotConfigured):
        create_default_app()


def test_import_coordinator_app_stays_light():
    root = Path(__file__).resolve().parents[2]
    code = (
        "import sys, coordinator.app; "
        "assert not ({'torch','vllm','unsloth'} & set(sys.modules))"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=str(root), capture_output=True, text=True, check=False
    )
    assert r.returncode == 0, r.stderr
