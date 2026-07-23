# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assemblage de la boucle du coordinateur à partir de la config et d'un client d'agent.

Sépare la logique de câblage (testable avec des doubles) de l'app FastAPI. Le
catalogue est découvert au démarrage depuis le `/capabilities` live du serveur
d'agents ; la conformance manifeste↔live (sous-projet C) s'applique. Politique
invalide ou aucun agent découvert → échec de démarrage fail-closed.
"""

from __future__ import annotations

import time
from typing import Any, Protocol
from uuid import uuid4

import yaml

from coordinator.agent_call import make_agent_call
from coordinator.catalog_builder import build_catalog
from coordinator.config import CoordinatorConfig
from coordinator.extractor import build_regex_extractor
from coordinator.loop import GatedLoop
from coordinator.proposer import ChatLLM, LlmProposer
from coordinator.session import EncryptedFileSessionStore
from core.approval.store import ApprovalStore
from core.audit.file_sink import FileAuditSink
from core.policy.loading import load_policy


class AssemblyError(Exception):
    """L'assemblage runtime a échoué (aucun agent, config incohérente)."""


class AgentClientLike(Protocol):
    async def get_capabilities(self) -> dict[str, Any]: ...
    async def execute_structured(self, function: str, args: dict[str, Any]) -> dict[str, Any]: ...


def discover_agents(caps: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Extrait {nom_agent: [capacités]} de la réponse /capabilities du serveur d'agents."""
    return {a["name"]: a["functions"] for a in caps.get("agents", [])}


async def assemble_loop(
    config: CoordinatorConfig, agent_clients: list[AgentClientLike], llm: ChatLLM
) -> GatedLoop:
    """Assemble une `GatedLoop` depuis la config et une liste de clients d'agent.

    Interroge le `/capabilities` de chaque serveur, fusionne les agents et route
    chaque agent vers le client qui l'héberge. Deux serveurs exposant le même nom
    d'agent → `AssemblyError` (routage ambigu). Construit le catalogue (conformance
    C), charge la politique (fail-closed), câble l'audit borné et les composants.

    Raises:
        AssemblyError: aucun agent découvert, ou collision de nom d'agent.
        ManifestConformanceError: drift manifeste↔live.
        PolicyError: règle malformée ou glob ne couvrant aucune capacité connue.
    """
    live: dict[str, list[dict[str, Any]]] = {}
    agent_to_client: dict[str, AgentClientLike] = {}
    for client in agent_clients:
        caps = await client.get_capabilities()
        for name, funcs in discover_agents(caps).items():
            if name in agent_to_client:
                raise AssemblyError(
                    f"agent '{name}' exposé par plusieurs serveurs (routage ambigu)"
                )
            live[name] = funcs
            agent_to_client[name] = client
    if not live:
        raise AssemblyError("aucun agent découvert sur les serveurs d'agents")
    catalog = await build_catalog(list(live), live)  # conformance C ; drift → refus
    raw = yaml.safe_load(config.policy_file.read_text(encoding="utf-8")) or {}
    policy = load_policy(raw.get("rules", []), catalog)  # fail-closed sur règle/glob invalide
    return GatedLoop(
        proposer=LlmProposer(llm=llm, catalog=catalog),
        catalog=catalog,
        policy=policy,
        sink=FileAuditSink(
            config.audit_file,
            max_bytes=config.audit_max_bytes,
            backup_count=config.audit_backups,
        ),
        approvals=ApprovalStore(),
        sessions=EncryptedFileSessionStore(config.session_dir, config.session_key),
        call=make_agent_call(agent_to_client),
        extract=build_regex_extractor(),
        clock=time.time,
        id_factory=lambda: uuid4().hex,
    )
