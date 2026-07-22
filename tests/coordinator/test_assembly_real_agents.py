"""Régression : assemblage contre la forme réelle du serveur d'agents (3 agents).

`server.py` expose crowdsec + opnsense + wireguard. `build_catalog` charge le
manifeste de CHAQUE agent découvert (agents/manifest.load_manifest). Si un
manifeste manque (ex. wireguard.yml absent), `assemble_loop` lève
`FileNotFoundError` au démarrage — un vrai `docker compose up` casse alors
que les tests unitaires à 1-2 agents restaient verts. Ce test reproduit la
forme exacte du serveur réel pour l'empêcher de régresser.
"""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from agents.crowdsec_agent import CrowdSecAgent
from agents.opnsense_agent import OPNsenseAgent
from agents.wireguard_agent import WireGuardAgent
from coordinator.assembly import assemble_loop
from coordinator.config import CoordinatorConfig
from coordinator.loop import GatedLoop


def _agent_entry(name, caps):
    return {"name": name, "tool_name": name, "functions": caps}


_WIREGUARD_CAPS = WireGuardAgent(model_path=None, simulation_mode=True).get_capabilities()

_CAPS = {"agents": [
    _agent_entry("crowdsec", CrowdSecAgent(model_path=None).get_capabilities()),
    _agent_entry("opnsense", OPNsenseAgent(model_path=None).get_capabilities()),
    _agent_entry("wireguard", _WIREGUARD_CAPS),
]}


class _Fake3AgentClient:
    async def get_capabilities(self):
        return _CAPS

    async def execute_structured(self, function, args):
        return {"ok": function}


class _FakeLLM:
    async def chat(self, messages, max_tokens=1024):
        return "{}"


def _cfg(tmp_path: Path) -> CoordinatorConfig:
    pol = tmp_path / "policy.yml"
    policy_text = (
        "rules:\n  - match: {capability: 'crowdsec.get_metrics'}\n    effect: allow\n"
    )
    pol.write_text(policy_text, encoding="utf-8")
    return CoordinatorConfig(
        auth_secret="s", session_key=Fernet.generate_key(), policy_file=pol,
        audit_file=tmp_path / "a.jsonl", session_dir=tmp_path / "s", host="127.0.0.1", port=8080,
        agent_server_url="http://x", agent_server_sock="", agent_server_key="",
        agent_servers=["http://x"], audit_max_bytes=0, audit_backups=0)


@pytest.mark.asyncio
async def test_assembles_against_real_three_agent_server(tmp_path: Path):
    # Prouve que le coordinateur assemble contre les 3 agents réels du serveur
    # (build_catalog charge crowdsec.yml + opnsense.yml + wireguard.yml).
    loop = await assemble_loop(_cfg(tmp_path), [_Fake3AgentClient()], _FakeLLM())
    assert isinstance(loop, GatedLoop)
