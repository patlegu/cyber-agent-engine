"""Adaptateur entre la frontière d'exécution de `core/` et le transport agent.

`core.execution.execute` appelle `call(capability, real_args)` avec une capacité
QUALIFIÉE (`crowdsec.ban_ip`). L'agent, lui, ne connaît que ses fonctions non
qualifiées. Cet adaptateur sépare le namespace, choisit le bon client, et délègue
à `execute_structured` (mode CAP v2, sans SLM).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

AgentCall = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]


class ClientLike(Protocol):
    """Protocole pour un client d'agent capable d'exécuter des fonctions structurées."""

    async def execute_structured(
        self, function: str, args: dict[str, Any]
    ) -> dict[str, Any]: ...


class UnknownAgent(Exception):
    """La capacité vise un agent absent de la table de clients."""


def make_agent_call(clients: Mapping[str, ClientLike]) -> AgentCall:
    """Crée une fonction de routage qui dirige les capacités qualifiées vers les bons clients.

    Args:
        clients: Dictionnaire des clients disponibles par nom d'agent.

    Returns:
        Une fonction asynchrone qui prend une capacité qualifiée et des arguments,
        sépare le namespace, et appelle le bon client.

    Raises:
        UnknownAgent: Si l'agent n'est pas trouvé ou si la capacité n'a pas de point.
    """

    async def _call(capability: str, args: dict[str, str]) -> dict[str, Any]:
        agent_name, _, function = capability.partition(".")
        if not function or agent_name not in clients:
            raise UnknownAgent(capability)
        return await clients[agent_name].execute_structured(function, args)

    return _call
