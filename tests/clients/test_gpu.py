import builtins

import pytest

from clients.gpu import GpuExtraRequired, load_native_vllm_client


def test_missing_extra_raises_clear_error(monkeypatch):
    real_import = builtins.__import__

    def _fake_import(name, *a, **k):
        if name.startswith(("clients.native_vllm_client", "vllm")) or name == "torch":
            raise ImportError("No module named 'torch'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(GpuExtraRequired) as exc:
        load_native_vllm_client()
    assert "[gpu]" in str(exc.value)
