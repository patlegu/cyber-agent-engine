import itertools
import json
import re

import pytest

from agents.crowdsec_agent import CrowdSecAgent
from coordinator.agent_call import make_agent_call
from coordinator.loop import Completed, GatedLoop, Suspended
from coordinator.proposer import Act, Finish
from coordinator.session import MemorySessionStore
from core.approval.store import ApprovalStore
from core.audit.sink import MemoryAuditSink
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import Intention, Match, Rule

REAL_IP = "203.0.113.9"


class _AgentClientAdapter:
    """Expose un CrowdSecAgent réel via l'interface execute_structured (mode simulation)."""

    def __init__(self, agent):
        self._agent = agent

    async def execute_structured(self, function, args):
        res = await self._agent.execute_direct(function, args)
        return {"success": res.success, "function": res.function, "result": res.result}


class _Proposer:
    def __init__(self):
        self._seen = []
        self._step = 0

    async def propose(self, request_tokens, history):
        self._seen.append((request_tokens, list(history)))
        self._step += 1
        if self._step == 1:
            # L'IP réelle a été tokenisée ; le LLM propose avec le jeton.
            token = re.search(r"IP_\d+", request_tokens).group(0)
            return Act(intention=Intention(capability="crowdsec.ban_ip", args={"ip": token}))
        return Finish(summary="IP bannie")

    def leaked(self):
        return REAL_IP in json.dumps(self._seen, ensure_ascii=False)


@pytest.mark.asyncio
async def test_end_to_end_ban_with_approval_no_pii_leak():
    agent = CrowdSecAgent(model_path=None)  # simulation : pas de LAPI
    call = make_agent_call({"crowdsec": _AgentClientAdapter(agent)})
    proposer = _Proposer()
    sink = MemoryAuditSink()
    approvals = ApprovalStore()
    policy = [Rule(match=Match(capability="crowdsec.ban_ip"), effect="approve")]

    ids = itertools.count(1)
    loop = GatedLoop(
        proposer=proposer,
        catalog=CapabilityCatalog([Capability(name="crowdsec.ban_ip", required_args=["ip"])]),
        policy=policy, sink=sink, approvals=approvals, sessions=MemorySessionStore(),
        call=call, extract=lambda t: {"IP": re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", t)},
        clock=lambda: 0.0, id_factory=lambda: f"a{next(ids)}",
    )

    suspended = await loop.handle(f"banni l'IP {REAL_IP}")
    assert isinstance(suspended, Suspended)

    approvals.approve(suspended.approval_id, approvals.get(suspended.approval_id).intention_hash)
    done = await loop.resume(suspended.approval_id)
    assert isinstance(done, Completed)
    # L'exécution réelle a reçu la vraie IP (mode simulation renvoie status banned).
    assert done.results[0]["result"]["status"] == "banned"

    # Non-régression PII : ni le LLM ni l'audit ne voient l'IP réelle.
    assert not proposer.leaked()
    audit_blob = json.dumps([e.model_dump() for e in sink.entries], ensure_ascii=False)
    assert REAL_IP not in audit_blob
    # L'audit ne porte que des jetons pour l'arg ip.
    ban_entries = [e for e in sink.entries if e.capability == "crowdsec.ban_ip"]
    assert ban_entries and all(re.fullmatch(r"IP_\d+", e.args.get("ip", "")) for e in ban_entries)
