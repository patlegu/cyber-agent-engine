from typing import Any

import pytest

from core.approval.store import ApprovalNotFound, ApprovalStore
from core.audit.sink import MemoryAuditSink
from core.execution.authorization import NotAuthorized
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


async def test_resume_inconnu_leve_approval_not_found() -> None:
    _, call = _calls()
    orch = TrustOrchestrator(
        policy=[], catalog=_catalog(), extract=_extract,
        proposer=_Proposer(Intention(capability="crowdsec.add_ban", args={"ip": "IP_1"})),
        call=call, sink=MemoryAuditSink(), approvals=ApprovalStore(),
    )
    with pytest.raises(ApprovalNotFound):
        await orch.resume("appr-inconnu")


async def test_resume_non_approuve_est_audite_et_refuse() -> None:
    seen, call = _calls()
    sink = MemoryAuditSink()
    policy = [Rule(match=Match(capability="opnsense.add_nat"), effect="approve")]
    approvals = ApprovalStore()
    orch = TrustOrchestrator(
        policy=policy, catalog=_catalog(), extract=_extract,
        proposer=_Proposer(Intention(capability="opnsense.add_nat", args={"interface": "lan"})),
        call=call, sink=sink, approvals=approvals,
    )
    out = await orch.handle("ajouter un nat")
    assert out.approval_id is not None
    before = len(sink.entries)
    with pytest.raises(NotAuthorized):
        await orch.resume(out.approval_id)  # jamais approuve -> refus
    assert seen == []  # rien execute
    assert any(e.event == "resume_refuse" for e in sink.entries[before:])  # tentative auditee


async def test_reject_nettoie_le_vault_et_audite() -> None:
    _, call = _calls()
    sink = MemoryAuditSink()
    policy = [Rule(match=Match(capability="opnsense.add_nat"), effect="approve")]
    approvals = ApprovalStore()
    orch = TrustOrchestrator(
        policy=policy, catalog=_catalog(), extract=_extract,
        proposer=_Proposer(Intention(capability="opnsense.add_nat", args={"interface": "lan"})),
        call=call, sink=sink, approvals=approvals,
    )
    out = await orch.handle("ajouter un nat")
    assert out.approval_id is not None and out.approval_id in orch._vaults
    rejected = orch.reject(out.approval_id)
    assert rejected.status == "denied"
    assert out.approval_id not in orch._vaults  # vault de session nettoye
    assert any(e.event == "rejected" for e in sink.entries)
