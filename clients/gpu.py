# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chargement paresseux des composants GPU, avec message d'erreur lisible.

Le loader vLLM in-process (`NativeVLLMClient`) tire torch+vllm. On ne l'importe
JAMAIS au chargement d'un module : uniquement à la demande, via ce helper, qui
transforme un `ImportError` brut en une erreur explicite indiquant l'extra `[gpu]`.
"""

from __future__ import annotations

from typing import Any


class GpuExtraRequired(RuntimeError):
    """Une fonctionnalité GPU (loader vLLM in-process) a été demandée sans l'extra [gpu]."""


def load_native_vllm_client() -> Any:
    try:
        from clients.native_vllm_client import NativeVLLMClient  # noqa: PLC0415
    except ImportError as exc:
        raise GpuExtraRequired(
            "The in-process vLLM loader requires the GPU extra: "
            "pip install cyber-agent-engine[gpu]"
        ) from exc
    return NativeVLLMClient
