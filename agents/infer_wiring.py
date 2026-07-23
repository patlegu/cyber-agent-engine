# SPDX-License-Identifier: AGPL-3.0-or-later
"""Câblage du backend d'inférence NL des agents depuis l'environnement.

Construit un OpenAICompatClient partagé (si AGENT_INFER_BASE_URL est défini) et
résout le nom de LoRA par agent. Le serveur d'agents injecte ces valeurs dans
chaque ToolAgent (params openai_client/lora_model livrés en C).
"""

from __future__ import annotations

from collections.abc import Mapping

from clients.openai_compat_client import OpenAICompatClient


def resolve_lora_models(env: Mapping[str, str]) -> dict[str, str]:
    """Mappe agent → nom de LoRA. `<AGENT>_LORA_MODEL` prime sur `AGENT_LORA_MODELS`."""
    models: dict[str, str] = {}
    global_map = env.get("AGENT_LORA_MODELS", "")
    for pair in global_map.split(","):
        if "=" in pair:
            name, _, model = pair.partition("=")
            name, model = name.strip(), model.strip()
            if name and model:
                models[name] = model
    for key, value in env.items():
        if key.endswith("_LORA_MODEL") and value:
            agent = key[: -len("_LORA_MODEL")].lower()
            models[agent] = value
    return models


def build_infer_client(env: Mapping[str, str]) -> OpenAICompatClient | None:
    """Construit le client d'inférence partagé si un endpoint est configuré, sinon None."""
    base_url = env.get("AGENT_INFER_BASE_URL", "")
    if not base_url:
        return None
    return OpenAICompatClient(base_url=base_url, api_key=env.get("AGENT_INFER_API_KEY", ""))
