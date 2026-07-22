import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from agents.crowdsec_agent import CrowdSecAgent
from coordinator.assembly import AssemblyError, assemble_loop, discover_agents
from coordinator.config import CoordinatorConfig
from coordinator.loop import GatedLoop, Suspended
from core.policy.loading import PolicyError

# IMPORTANT : les capacités live doivent correspondre au manifeste crowdsec.yml
# (15 fonctions) sinon build_catalog->check_conformance (sous-projet C) refuse.
# On les prend donc de l'agent réel (mode simulation, sans LAPI).
_CROWDSEC_FUNCS = CrowdSecAgent(model_path=None).get_capabilities()
_CAPS = {"agents": [{"name": "crowdsec", "tool_name": "crowdsec", "functions": _CROWDSEC_FUNCS}]}


class _FakeClient:
    async def get_capabilities(self):
        return _CAPS

    async def execute_structured(self, function, args):
        return {"status": "banned", "fn": function}


class _FakeLLM:
    def __init__(self, replies):
        self._it = iter(replies)

    async def chat(self, messages, max_tokens=1024):
        return next(self._it)


def _cfg(tmp_path: Path, policy_text: str) -> CoordinatorConfig:
    pol = tmp_path / "policy.yml"
    pol.write_text(policy_text, encoding="utf-8")
    return CoordinatorConfig(
        auth_secret="s", session_key=Fernet.generate_key(), policy_file=pol,
        audit_file=tmp_path / "audit.jsonl", session_dir=tmp_path / "sessions",
        host="127.0.0.1", port=8080, agent_server_url="http://x", agent_server_sock="",
        agent_server_key="",
    )


def test_discover_agents():
    names = {f["name"] for f in discover_agents(_CAPS)["crowdsec"]}
    assert "ban_ip" in names and "get_metrics" in names


@pytest.mark.asyncio
async def test_assemble_loop_builds_a_working_loop(tmp_path: Path):
    policy = (
        "rules:\n  - match: {capability: 'crowdsec.ban_ip'}\n"
        "    effect: approve\n    reason: r\n"
    )
    cfg = _cfg(tmp_path, policy)
    llm = _FakeLLM([
        json.dumps({"action": {"capability": "crowdsec.ban_ip", "args": {"ip": "IP_1"}}}),
        json.dumps({"final": "ok"}),
    ])
    loop = await assemble_loop(cfg, _FakeClient(), llm)
    assert isinstance(loop, GatedLoop)
    res = await loop.handle("banni 203.0.113.9")
    assert isinstance(res, Suspended)
    assert cfg.audit_file.exists()  # FileAuditSink a écrit


@pytest.mark.asyncio
async def test_invalid_policy_refuses(tmp_path: Path):
    # glob ne couvrant aucune capacité connue -> load_policy lève -> assemble échoue
    cfg = _cfg(tmp_path, "rules:\n  - match: {capability: 'inconnu.*'}\n    effect: allow\n")
    with pytest.raises(PolicyError):
        await assemble_loop(cfg, _FakeClient(), _FakeLLM([]))


@pytest.mark.asyncio
async def test_no_agents_discovered_refuses(tmp_path: Path):
    class _Empty:
        async def get_capabilities(self):
            return {"agents": []}

        async def execute_structured(self, function, args):
            return {}

    cfg = _cfg(tmp_path, "rules: []\n")
    with pytest.raises(AssemblyError):
        await assemble_loop(cfg, _Empty(), _FakeLLM([]))
