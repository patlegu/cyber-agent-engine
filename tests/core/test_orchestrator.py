from typing import Any

from core.approval.store import ApprovalStore
from core.audit.sink import MemoryAuditSink
from core.orchestrator import TrustOrchestrator
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import ArgMatch, Intention, Match, Rule


def _extract(text: str) -> dict[str, list[str]]:
    return {"IP": [t for t in text.replace(",", " ").split() if t.count(".") == 3]}


def _catalog() -> CapabilityCatalog:
    return CapabilityCatalog([
        Capability(name="crowdsec.add_ban", required_args=["ip"]),
        Capability(name="opnsense.add_nat", required_args=["interface"]),
    ])


class _Proposer:
    """Faux LLM : renvoie une intention scriptée (déjà tokenisée par l'orchestrateur)."""

    def __init__(self, intention: Intention) -> None:
        self._it = intention

    async def propose(self, prompt: str) -> Intention:
        # Vérifie au passage que le prompt est tokenisé (aucune IP réelle).
        assert "10.0.0.5" not in prompt
        return self._it


def _calls() -> tuple[list[dict[str, str]], Any]:
    seen: list[dict[str, str]] = []

    async def call(capability: str, args: dict[str, str]) -> dict[str, str]:
        seen.append({"capability": capability, **args})
        return {"status": "ok"}

    return seen, call


async def test_allow_execute_et_detokenise() -> None:
    seen, call = _calls()
    sink = MemoryAuditSink()
    policy = [Rule(match=Match(capability="crowdsec.add_ban"), effect="allow")]
    orch = TrustOrchestrator(
        policy=policy, catalog=_catalog(), extract=_extract,
        proposer=_Proposer(Intention(capability="crowdsec.add_ban", args={"ip": "IP_1"})),
        call=call, sink=sink, approvals=ApprovalStore(),
    )
    out = await orch.handle("bannir 10.0.0.5")
    assert out.status == "executed"
    assert seen == [{"capability": "crowdsec.add_ban", "ip": "10.0.0.5"}]
    # L'audit ne porte que des jetons.
    assert all("10.0.0.5" not in e.model_dump_json() for e in sink.entries)


async def test_deny_n_execute_rien() -> None:
    seen, call = _calls()
    orch = TrustOrchestrator(
        policy=[], catalog=_catalog(), extract=_extract,
        proposer=_Proposer(Intention(capability="crowdsec.add_ban", args={"ip": "IP_1"})),
        call=call, sink=MemoryAuditSink(), approvals=ApprovalStore(),
    )
    out = await orch.handle("bannir 10.0.0.5")
    assert out.status == "denied" and seen == []


async def test_approve_suspend_puis_resume_execute() -> None:
    seen, call = _calls()
    policy = [Rule(match=Match(capability="opnsense.add_nat"), effect="approve")]
    approvals = ApprovalStore()
    orch = TrustOrchestrator(
        policy=policy, catalog=_catalog(), extract=_extract,
        proposer=_Proposer(Intention(capability="opnsense.add_nat", args={"interface": "lan"})),
        call=call, sink=MemoryAuditSink(), approvals=approvals,
    )
    out = await orch.handle("ajouter un nat")
    assert out.status == "pending_approval" and out.approval_id is not None
    assert seen == []  # rien exécuté tant que non approuvé
    ap = approvals.get(out.approval_id)
    assert ap is not None
    approvals.approve(ap.id, ap.intention_hash)
    resumed = await orch.resume(out.approval_id)
    assert resumed.status == "executed" and len(seen) == 1
