"""Client d'inférence OpenAI-compatible (HTTP) — sert un LoRA sans dépendance GPU.

Sert de transport pour le chemin NL d'un agent : POST /chat/completions vers un
endpoint OpenAI-compatible (vLLM multi-LoRA, llama.cpp, Ollama /v1…), le `model`
étant le nom du LoRA de l'outil. Aucune dépendance lourde (juste httpx).
"""

from __future__ import annotations

from typing import Any

import httpx


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url, headers=headers, timeout=httpx.Timeout(timeout)
        )

    async def chat(self, messages: list[dict[str, Any]], model: str, max_tokens: int = 256) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.1,
        }
        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return str(data["choices"][0]["message"]["content"])

    async def aclose(self) -> None:
        await self._client.aclose()
