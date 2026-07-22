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
    config: CoordinatorConfig, agent_client: AgentClientLike, llm: ChatLLM
) -> GatedLoop:
    """Assemble une `GatedLoop` prête à l'emploi depuis la config et un client d'agent.

    Découvre les agents joignables (`/capabilities`), construit le catalogue
    (manifestes déclarés + conformance live pour C), charge la politique
    (fail-closed sur règle/glob invalide) et câble les composants (audit,
    sessions, approbations, proposer LLM, extracteur regex).

    Raises:
        AssemblyError: aucun agent découvert sur le serveur d'agents.
        ManifestConformanceError: drift entre le manifeste déclaré et le live.
        PolicyError: règle malformée ou glob ne couvrant aucune capacité connue.
    """
    caps = await agent_client.get_capabilities()
    live = discover_agents(caps)
    if not live:
        raise AssemblyError("aucun agent découvert sur le serveur d'agents")
    catalog = await build_catalog(list(live), live)  # conformance C ; drift → refus
    raw = yaml.safe_load(config.policy_file.read_text(encoding="utf-8")) or {}
    policy = load_policy(raw.get("rules", []), catalog)  # fail-closed sur règle/glob invalide
    return GatedLoop(
        proposer=LlmProposer(llm=llm, catalog=catalog),
        catalog=catalog,
        policy=policy,
        sink=FileAuditSink(config.audit_file),
        approvals=ApprovalStore(),
        sessions=EncryptedFileSessionStore(config.session_dir, config.session_key),
        call=make_agent_call({name: agent_client for name in live}),
        extract=build_regex_extractor(),
        clock=time.time,
        id_factory=lambda: uuid4().hex,
    )
