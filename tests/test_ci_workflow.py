from pathlib import Path
import yaml

_ROOT = Path(__file__).resolve().parent.parent


def _wf() -> dict:
    return yaml.safe_load((_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))


def _on(wf: dict):
    # PyYAML interprète la clé `on:` comme le booléen True (YAML 1.1).
    return wf.get(True, wf.get("on"))


def test_triggers_push_and_pr():
    on = _on(_wf())
    assert "push" in on and "pull_request" in on


def test_has_test_job_running_gates():
    jobs = _wf()["jobs"]
    assert "test" in jobs
    steps_text = yaml.dump(jobs["test"])
    assert ".[dev]" in steps_text          # install éditable avec extra dev
    assert "ruff check" in steps_text       # gate ruff
    assert "mypy" in steps_text             # gate mypy
    assert "pytest" in steps_text           # gate pytest


def test_ruff_gate_is_scoped_not_whole_repo():
    steps_text = yaml.dump(_wf()["jobs"]["test"])
    # ne doit PAS lancer `ruff check .` (689 findings legacy)
    assert "ruff check ." not in steps_text
