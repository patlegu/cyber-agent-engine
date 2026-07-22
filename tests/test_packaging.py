import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _cfg() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


def test_core_deps_have_no_heavy_ml():
    deps = _cfg()["project"]["dependencies"]
    joined = " ".join(deps).lower()
    for heavy in ("torch", "vllm", "unsloth"):
        assert heavy not in joined, f"{heavy} ne doit pas être une dep core"
    for needed in ("fastapi", "requests", "anthropic"):
        assert any(needed in d.lower() for d in deps), f"{needed} manquant des deps core"


def test_gpu_extra_declared():
    extras = _cfg()["project"].get("optional-dependencies", {})
    assert "gpu" in extras
    joined = " ".join(extras["gpu"]).lower()
    assert "torch" in joined and "vllm" in joined and "unsloth" in joined


def test_packages_include_covers_runtime():
    include = _cfg()["tool"]["setuptools"]["packages"]["find"]["include"]
    for pkg in ("clients*", "agents*", "coordinator*", "core*"):
        assert pkg in include
