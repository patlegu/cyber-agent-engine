# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test d'intégration bout-en-bout T4 : la boucle câble la légende (proposer) et
`arg_meta` (decide) depuis le vault, sans que le moteur de politique
(`core/policy/engine.py`) n'ait besoin de connaître la notion de scope.

Une IP privée est refusée par la politique AVANT même d'atteindre le pas
d'approbation humaine (`deny` sur `ip__scope == private`) ; une IP publique
traverse cette même règle et atteint le gate d'approbation (`Suspended`).
"""

from __future__ import annotations

import itertools
import re

import pytest

from coordinator.loop import Denied, GatedLoop, Suspended
from coordinator.proposer import Act, Finish
from coordinator.session import MemorySessionStore
from core.approval.store import ApprovalStore
from core.audit.sink import MemoryAuditSink
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import ArgMatch, Intention, Match, Rule

# Règle de politique : refuse toute IP de scope privé, sans que le moteur ne
# connaisse la notion de "scope" — c'est `decide` (T2) qui injecte le pseudo-arg
# synthétique `ip__scope` depuis `arg_meta` fourni par la boucle (T4).
_DENY_PRIVATE = Rule(
    match=Match(
        capability="opnsense.block_*",
        args={"ip__scope": ArgMatch(op="eq", value="private")},
    ),
    effect="deny",
    reason="ip privée",
)
_APPROVE_FALLBACK = Rule(match=Match(capability="opnsense.block_*"), effect="approve")


def _extract(text: str) -> dict[str, list[str]]:
    return {"IP_ADDRESS": re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", text)}


class _RecordingProposer:
    """Propose toujours `opnsense.block_ip(ip=<premier jeton IP du texte>)` et
    enregistre le `context` (légende) reçu à chaque appel — permet de vérifier que
    la légende ne contient jamais l'adresse réelle."""

    def __init__(self) -> None:
        self.contexts: list[str] = []
        self._done = False

    async def propose(self, request_tokens: str, history: list[str], *, context: str = ""):
        self.contexts.append(context)
        if self._done:
            return Finish(summary="fait")
        self._done = True
        token = re.search(r"IP_ADDRESS_\d+", request_tokens)
        assert token is not None
        return Act(
            intention=Intention(capability="opnsense.block_ip", args={"ip": token.group(0)})
        )


def _ids():
    counter = itertools.count(1)
    return lambda: f"appr-{next(counter)}"


def _loop_factory(policy: list[Rule]) -> tuple[GatedLoop, _RecordingProposer]:
    proposer = _RecordingProposer()

    async def _noop_call(cap, args):
        return {"ok": cap, "args": args}

    loop = GatedLoop(
        proposer=proposer,
        catalog=CapabilityCatalog([Capability(name="opnsense.block_ip", required_args=["ip"])]),
        policy=policy,
        sink=MemoryAuditSink(),
        approvals=ApprovalStore(),
        sessions=MemorySessionStore(),
        call=_noop_call,
        extract=_extract,
        clock=lambda: 0.0,
        id_factory=_ids(),
        max_steps=5,
        session_ttl=300.0,
    )
    return loop, proposer


@pytest.mark.asyncio
async def test_loop_denies_private_ip_before_gate():
    loop, proposer = _loop_factory([_DENY_PRIVATE, _APPROVE_FALLBACK])
    result = await loop.handle("bloque 10.0.0.5")
    assert isinstance(result, Denied)
    # Refusé par la politique, jamais transmis au gate d'approbation humaine.
    assert "opnsense.block_ip" in result.reason
    # Zéro-secret : la légende envoyée au proposeur ne contient jamais l'adresse.
    assert all("10.0.0.5" not in ctx for ctx in proposer.contexts)


@pytest.mark.asyncio
async def test_loop_gates_public_ip():
    loop, proposer = _loop_factory([_DENY_PRIVATE, _APPROVE_FALLBACK])
    result = await loop.handle("bloque 8.8.8.8")
    assert isinstance(result, Suspended)
    assert all("8.8.8.8" not in ctx for ctx in proposer.contexts)


@pytest.mark.asyncio
async def test_legend_carries_family_and_scope_never_the_address():
    loop, proposer = _loop_factory([_DENY_PRIVATE, _APPROVE_FALLBACK])
    await loop.handle("bloque 10.0.0.5")
    assert proposer.contexts, "le proposeur doit avoir reçu au moins un appel"
    legend = proposer.contexts[0]
    assert legend == "IP_ADDRESS_1 = IPv4 private"
    assert "10.0.0.5" not in legend
