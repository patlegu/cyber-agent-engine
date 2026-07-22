"""Non-régression : la raison de la règle qui a routé vers `approve` doit survivre
jusqu'aux entrées d'audit post-approbation (`executed_after_approval`, `resume_refuse`,
`rejected`), qui reconstruisaient auparavant un `Verdict(matched_rule=None)` et
perdaient l'information.
"""

from __future__ import annotations

import itertools

import pytest

from coordinator.loop import Completed, GatedLoop, Suspended
from coordinator.proposer import Act, Finish
from coordinator.session import MemorySessionStore
from core.approval.store import ApprovalStore
from core.audit.sink import MemoryAuditSink
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import Intention, Match, Rule


class _Proposer:
    def __init__(self, seq):
        self._it = iter(seq)

    async def propose(self, request_tokens, history):
        return next(self._it)


def _ids():
    counter = itertools.count(1)
    return lambda: f"a{next(counter)}"


@pytest.mark.asyncio
async def test_audit_post_approval_carries_rule_reason():
    proposer = _Proposer(
        [
            Act(intention=Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"})),
            Finish(summary="banni"),
        ]
    )
    policy = [
        Rule(
            match=Match(capability="crowdsec.ban_ip"),
            effect="approve",
            reason="ban requiert validation",
        )
    ]
    sink = MemoryAuditSink()
    approvals = ApprovalStore()

    async def _call(cap, args):
        return {"status": "banned"}

    loop = GatedLoop(
        proposer=proposer,
        catalog=CapabilityCatalog([Capability(name="crowdsec.ban_ip", required_args=["ip"])]),
        policy=policy,
        sink=sink,
        approvals=approvals,
        sessions=MemorySessionStore(),
        call=_call,
        extract=lambda t: {"IP": ["203.0.113.9"]} if "203" in t else {},
        clock=lambda: 0.0,
        id_factory=_ids(),
    )
    res = await loop.handle("banni 203.0.113.9")
    assert isinstance(res, Suspended)
    approvals.approve(res.approval_id, approvals.get(res.approval_id).intention_hash)
    res2 = await loop.resume(res.approval_id)
    assert isinstance(res2, Completed)
    post = [e for e in sink.entries if e.event == "executed_after_approval"]
    assert post and post[0].rule_reason == "ban requiert validation"
