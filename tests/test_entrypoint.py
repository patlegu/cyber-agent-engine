import tomllib
from pathlib import Path

import yaml

from coordinator.app import run

_ROOT = Path(__file__).resolve().parent.parent


def _cfg() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_console_script_declared():
    scripts = _cfg()["project"].get("scripts", {})
    assert scripts.get("cyber-coordinator") == "coordinator.app:run"


def test_uvicorn_is_core_dep():
    deps = " ".join(_cfg()["project"]["dependencies"]).lower()
    assert "uvicorn" in deps


def test_run_is_importable():
    assert callable(run)


def test_example_policy_is_valid_yaml_with_rules():
    data = yaml.safe_load((_ROOT / "policy.example.yml").read_text(encoding="utf-8"))
    assert isinstance(data.get("rules"), list) and data["rules"]
