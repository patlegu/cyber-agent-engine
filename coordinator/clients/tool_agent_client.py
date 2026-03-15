"""
coordinator/clients/tool_agent_client.py — Client HTTP vers le tool-agent-server.

Encapsule tous les appels vers http://localhost:3000 :
- GET  /capabilities              (cache 60 s)
- POST /agent/execute (naturel)   commande en langage naturel → vLLM de l'agent interprète
- POST /agent/execute (CAP v1)    paquet CoordinatorDirective → SLM entraîné sur format CAP
- POST /agent/execute (structuré) function + args directs → bypass LLM, exécution immédiate

Toutes les réponses sont validées via le modèle Pydantic AgentExecuteResponse
(défini dans agents/contracts.py) — une réponse malformée lève une ValidationError
au lieu de passer silencieusement.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from pydantic import ValidationError

# Accès au package agents/ depuis le répertoire parent
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agents.contracts import AgentExecuteRequest, AgentExecuteResponse

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_RETRY_BACKOFF = 1.0   # secondes


class ToolAgentError(Exception):
    """Erreur non-récupérable retournée par un agent-outil."""
    def __init__(self, message: str, error_code: Optional[str] = None):
        super().__init__(message)
        self.error_code = error_code


class ToolAgentClient:
    """
    Client asynchrone vers le tool-agent-server (port 3000).

    Usage :
        async with ToolAgentClient(base_url, api_key) as client:
            caps = await client.get_capabilities()
            result = await client.execute("ban IP 1.2.3.4")
            result = await client.execute_structured("delete_filter_rule", {"uuid": "..."})
    """

    def __init__(self, base_url: str = "http://localhost:3000", api_key: str = "", socket_path: str = ""):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._socket_path = socket_path  # UDS : chemin vers le fichier socket
        self._client: Optional[httpx.AsyncClient] = None
        self._capabilities_cache: Optional[dict] = None
        self._capabilities_ts: float = 0.0
        self._capabilities_ttl: float = 60.0

    async def __aenter__(self):
        headers = {"X-API-Key": self._api_key} if self._api_key else {}
        if self._socket_path:
            # Transport UDS — pas de TCP, le hostname dans base_url est ignoré
            transport = httpx.AsyncHTTPTransport(uds=self._socket_path)
            self._client = httpx.AsyncClient(
                transport=transport,
                base_url="http://agent",
                headers=headers,
                timeout=httpx.Timeout(30.0),
            )
            logger.info("ToolAgentClient: UDS transport → %s", self._socket_path)
        else:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=httpx.Timeout(30.0),
            )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Capabilities (avec cache 60 s)
    # ------------------------------------------------------------------

    async def get_capabilities(self) -> dict:
        """Retourne le schéma de toutes les fonctions disponibles sur le serveur."""
        now = time.monotonic()
        if self._capabilities_cache and (now - self._capabilities_ts) < self._capabilities_ttl:
            return self._capabilities_cache

        resp = await self._client.get("/capabilities")
        resp.raise_for_status()
        self._capabilities_cache = resp.json()
        self._capabilities_ts = now
        logger.info(
            "Capabilities refreshed: %d agents",
            len(self._capabilities_cache.get("agents", [])),
        )
        return self._capabilities_cache

    # ------------------------------------------------------------------
    # Execute — méthode interne partagée
    # ------------------------------------------------------------------

    async def _post_execute(self, payload: dict) -> AgentExecuteResponse:
        """
        Envoie POST /agent/execute et valide la réponse via Pydantic.

        Gère le retry sur API_UNREACHABLE et lève ToolAgentError sur
        PERMISSION_DENIED ou après épuisement des tentatives.
        """
        for attempt in range(1, _MAX_RETRIES + 2):
            try:
                resp = await self._client.post("/agent/execute", json=payload)
                raw = resp.json()
            except httpx.TimeoutException as exc:
                if attempt <= _MAX_RETRIES:
                    logger.warning("Timeout (attempt %d/%d), retrying…", attempt, _MAX_RETRIES + 1)
                    await asyncio.sleep(_RETRY_BACKOFF * attempt)
                    continue
                raise ToolAgentError("Tool agent unreachable after retries", "API_UNREACHABLE") from exc

            # Validation Pydantic — lève ValidationError si le schéma est incorrect
            try:
                response = AgentExecuteResponse(**raw)
            except ValidationError as exc:
                logger.error("Invalid response schema from tool-agent-server: %s", exc)
                raise ToolAgentError(
                    f"Tool agent returned invalid response schema: {exc}",
                    "EXECUTION_ERROR",
                ) from exc

            if response.is_permission_denied():
                raise ToolAgentError(
                    response.error or "Permission denied", "PERMISSION_DENIED"
                )

            if response.is_retryable() and attempt <= _MAX_RETRIES:
                logger.warning(
                    "API_UNREACHABLE from agent (attempt %d/%d), retrying…",
                    attempt, _MAX_RETRIES + 1,
                )
                await asyncio.sleep(_RETRY_BACKOFF * attempt)
                continue

            return response

        raise ToolAgentError("Tool agent unreachable after retries", "API_UNREACHABLE")

    # ------------------------------------------------------------------
    # Mode naturel
    # ------------------------------------------------------------------

    async def execute(self, command: str) -> dict:
        """
        Envoie une commande en langage naturel au tool-agent-server.

        Le vLLM de l'agent interprète la commande et appelle la fonction adéquate.
        Retourne le dict de la réponse validée (AgentExecuteResponse.model_dump()).
        """
        req = AgentExecuteRequest(command=command)
        response = await self._post_execute(req.model_dump(exclude_none=True))
        return response.model_dump()

    # ------------------------------------------------------------------
    # Mode structuré — bypass LLM
    # ------------------------------------------------------------------

    async def execute_cap(self, directive: "CoordinatorDirective") -> dict:
        """
        Envoie un paquet CAP v1 au tool-agent-server.

        Le paquet est sérialisé en JSON et transmis comme `command` (mode naturel),
        mais le SLM agent est entraîné sur le format CAP et génère directement
        un tool_call — sans interpréter du langage naturel.

        Utiliser quand la tâche dispose d'un champ `directive` (fonction résolue
        par le coordinateur lors de la planification).

        Args:
            directive: CoordinatorDirective — paquet CAP v1 prêt à envoyer.

        Returns:
            dict (AgentExecuteResponse sérialisée)
        """
        cap_json = directive.to_user_message()
        logger.info(
            "CAP call: directive=%s entities=%s args=%s",
            directive.directive,
            {k: v for k, v in directive.entities.items() if v},
            directive.args,
        )
        req = AgentExecuteRequest(command=cap_json)
        response = await self._post_execute(req.model_dump(exclude_none=True))
        return response.model_dump()

    async def execute_structured(self, function: str, args: dict[str, Any]) -> dict:
        """
        Appelle directement une fonction sur le tool-agent-server sans passer
        par le vLLM — aucune inférence LLM côté agent.

        Utiliser quand la fonction et les arguments sont déjà connus avec certitude
        (ex : après reformulation ayant résolu un UUID depuis des résultats précédents).

        Args:
            function: Nom exact de la fonction (ex: "delete_filter_rule")
            args:     Arguments de la fonction (ex: {"uuid": "f9ed38a8-..."})

        Returns:
            dict (AgentExecuteResponse sérialisée)
        """
        req = AgentExecuteRequest(function=function, args=args)
        logger.info("Structured call: %s(%s)", function, args)
        response = await self._post_execute(req.model_dump(exclude_none=True))
        return response.model_dump()
