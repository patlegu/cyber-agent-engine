"""
coordinator/llm/coordinator_llm.py — LLM de raisonnement du coordinateur.

Backends configurables via COORDINATOR_BACKEND :
  - "anthropic"      : Claude API (claude-sonnet-4-6) — recommandé, aucun service local requis
  - "openai"         : API OpenAI-compatible — fonctionne aussi avec vLLM HTTP (port 8000)
  - "vllm"           : NativeVLLMClient direct (instance séparée, charge Qwen2.5-7B)
  - "ollama"         : Ollama local (si disponible)

Variables d'environnement :
  COORDINATOR_BACKEND          = anthropic | openai | vllm | ollama   (défaut: anthropic)
  COORDINATOR_MODEL            = ID du modèle selon le backend
  ANTHROPIC_API_KEY            = clé API Anthropic
  OPENAI_API_KEY               = clé API OpenAI (ou token vLLM si mode openai → vLLM)
  OPENAI_BASE_URL              = URL de l'API OpenAI-compatible (défaut: https://api.openai.com/v1)
                                 Mettre http://localhost:8000/v1 pour pointer vers vLLM
  COORDINATOR_GPU_UTIL         = utilisation GPU si backend=vllm (défaut: 0.5)
  COORDINATOR_OLLAMA_MODEL     = modèle Ollama (défaut: qwen2.5:7b)
"""

import asyncio
import logging
import os
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Variables d'environnement
# ---------------------------------------------------------------------------
COORDINATOR_BACKEND = os.getenv("COORDINATOR_BACKEND", "anthropic")
COORDINATOR_MODEL   = os.getenv("COORDINATOR_MODEL", "")   # valeur par défaut selon backend

ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL     = COORDINATOR_MODEL or "claude-sonnet-4-6"

OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL     = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL        = COORDINATOR_MODEL or "gpt-4o-mini"

OLLAMA_BASE_URL     = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL        = os.getenv("COORDINATOR_OLLAMA_MODEL", "qwen2.5:7b")

VLLM_MODEL          = COORDINATOR_MODEL or "Qwen/Qwen2.5-7B-Instruct"


class CoordinatorLLM:
    """
    Abstraction LLM pour le raisonnement haut niveau du coordinateur.

    Usage :
        llm = CoordinatorLLM()
        await llm.init()
        text = await llm.chat([{"role": "user", "content": "..."}])
        await llm.shutdown()
    """

    def __init__(self):
        self._backend = COORDINATOR_BACKEND
        self._vllm: Optional[object]            = None
        self._http: Optional[httpx.AsyncClient] = None
        self._anthropic: Optional[object]       = None

    async def init(self) -> None:
        """Initialise le backend LLM sélectionné."""
        if self._backend == "anthropic":
            self._init_anthropic()
        elif self._backend == "openai":
            self._init_openai_client()
        elif self._backend == "vllm":
            await self._init_vllm()
        else:  # ollama
            self._http = httpx.AsyncClient(
                base_url=OLLAMA_BASE_URL,
                timeout=httpx.Timeout(120.0),
            )
            logger.info("CoordinatorLLM: Ollama backend (model=%s)", OLLAMA_MODEL)

    # ------------------------------------------------------------------
    # Initialisation par backend
    # ------------------------------------------------------------------

    def _init_anthropic(self) -> None:
        try:
            import anthropic
            self._anthropic = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            logger.info("CoordinatorLLM: Anthropic backend (model=%s)", ANTHROPIC_MODEL)
        except ImportError:
            raise RuntimeError("Package 'anthropic' manquant. Faites : pip install anthropic")

    def _init_openai_client(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=OPENAI_BASE_URL,
            timeout=httpx.Timeout(120.0),
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        logger.info(
            "CoordinatorLLM: OpenAI-compatible backend (url=%s, model=%s)",
            OPENAI_BASE_URL, OPENAI_MODEL,
        )

    async def _init_vllm(self) -> None:
        import sys
        from pathlib import Path
        root = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(root))
        from factory.clients.native_vllm_client import NativeVLLMClient

        gpu_util    = float(os.getenv("COORDINATOR_GPU_UTIL", "0.5"))
        max_model_len = int(os.getenv("VLLM_MAX_MODEL_LEN", "8192"))
        max_attempts  = 3

        for attempt in range(1, max_attempts + 1):
            # Reset le singleton si un init précédent a échoué partiellement.
            NativeVLLMClient._instance = None

            try:
                loop = asyncio.get_event_loop()
                self._vllm = await loop.run_in_executor(
                    None,
                    lambda: NativeVLLMClient(
                        model_path=VLLM_MODEL,
                        lora_adapters={},
                        gpu_utilization=gpu_util,
                        max_model_len=max_model_len,
                    ),
                )
                logger.info("CoordinatorLLM: vLLM backend (model=%s)", VLLM_MODEL)
                return
            except Exception as exc:
                # Race condition de démarrage : un autre processus vLLM (tool-agent)
                # libère de la VRAM pendant le torch.compile, ce qui dérègle le
                # profiling mémoire de vLLM. On attend et on réessaie.
                if attempt < max_attempts:
                    delay = 30 * attempt
                    logger.warning(
                        "vLLM init failed (attempt %d/%d), retrying in %ds: %s",
                        attempt, max_attempts, delay, exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("vLLM init failed after %d attempts: %s", max_attempts, exc)
                    raise RuntimeError(
                        f"Impossible d'initialiser vLLM pour le coordinateur : {exc}"
                    ) from exc

    # ------------------------------------------------------------------
    # Interface publique
    # ------------------------------------------------------------------

    async def chat(self, messages: List[dict], max_tokens: int = 1024) -> str:
        """
        Envoie une liste de messages et retourne la réponse texte brute.

        Args:
            messages: format OpenAI [{"role": "system"|"user"|"assistant", "content": "..."}]
            max_tokens: limite de tokens en sortie

        Returns:
            Texte brut du LLM (le caller est responsable du parsing JSON).
        """
        if self._backend == "anthropic":
            return await self._chat_anthropic(messages, max_tokens)
        if self._backend == "openai":
            return await self._chat_openai(messages, max_tokens)
        if self._backend == "vllm" and self._vllm:
            return await self._chat_vllm(messages, max_tokens)
        return await self._chat_ollama(messages, max_tokens)

    # ------------------------------------------------------------------
    # Implémentations par backend
    # ------------------------------------------------------------------

    async def _chat_anthropic(self, messages: List[dict], max_tokens: int) -> str:
        # Sépare le system prompt (Anthropic l'attend en dehors du tableau)
        system = ""
        user_messages = []
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
            else:
                user_messages.append(m)

        kwargs = dict(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            messages=user_messages,
        )
        if system:
            kwargs["system"] = system

        response = await self._anthropic.messages.create(**kwargs)
        return response.content[0].text

    async def _chat_openai(self, messages: List[dict], max_tokens: int) -> str:
        payload = {
            "model": OPENAI_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.1,
        }
        resp = await self._http.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def _chat_vllm(self, messages: List[dict], max_tokens: int) -> str:
        prompt = self._messages_to_prompt(messages)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._vllm.complete(prompt, adapter_name=None),
        )
        return result

    async def _chat_ollama(self, messages: List[dict], max_tokens: int) -> str:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1, "top_p": 0.9, "num_predict": max_tokens},
        }
        resp = await self._http.post("/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")

    def _messages_to_prompt(self, messages: List[dict]) -> str:
        """Convertit les messages chat en prompt texte pour vLLM natif."""
        parts = []
        for m in messages:
            role    = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                parts.append(f"<|system|>\n{content}<|end|>")
            elif role == "user":
                parts.append(f"<|user|>\n{content}<|end|>")
            elif role == "assistant":
                parts.append(f"<|assistant|>\n{content}<|end|>")
        parts.append("<|assistant|>")
        return "\n".join(parts)

    async def shutdown(self) -> None:
        if self._vllm and hasattr(self._vllm, "shutdown"):
            self._vllm.shutdown()
        if self._http:
            await self._http.aclose()
