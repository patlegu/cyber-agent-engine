# tests/test_dockerfile_gpu.py
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_gpu_dockerfile_cuda_base_gpu_extra_nonroot():
    df = (_ROOT / "Dockerfile.gpu").read_text(encoding="utf-8")
    assert "nvidia/cuda" in df                       # base CUDA
    assert ".[gpu]" in df                              # installe l'extra gpu
    assert "USER appuser" in df                        # non-root
    assert not re.search(r'ENV\s+\w*(KEY|SECRET|TOKEN)\w*\s*=\s*\S+', df)  # pas de secret
