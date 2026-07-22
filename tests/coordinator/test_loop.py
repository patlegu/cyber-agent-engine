import itertools
import json
import re

import pytest

from coordinator.loop import Completed, Denied, Failed, GatedLoop, Suspended
from coordinator.proposer import Act, Finish, ProposerError
from coordinator.session import MemorySessionStore
from core.approval.store import ApprovalStore
from core.audit.sink import MemoryAuditSink
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import Intention, Match, Rule


def _catalog():
    return CapabilityCatalog([
        Capability(name="crowdsec.ban_ip", required_args=["ip"]),
        Capability(name="crowdsec.get_metrics", required_args=[]),
    ])


class _ScriptedProposer:
    """Renvoie une proposition scriptée par pas ; ignore le prompt."""
    def __init__(self, proposals):
        self._it = iter(proposals)

    async def propose(self, request_tokens, history):
        return next(self._it)


def _extract(text):
    # extracteur trivial : repère un motif IP factice pour la tokenisation
    return {"IP": re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", text)}


def _ids():
    counter = itertools.count(1)
    return lambda: f"appr-{next(counter)}"


def _loop(proposer, policy, *, call=None, sessions=None, clock=None):
    async def _noop_call(cap, args):
        return {"ok": cap, "args": args}
    return GatedLoop(
        proposer=proposer, catalog=_catalog(), policy=policy,
        sink=MemoryAuditSink(), approvals=ApprovalStore(),
        sessions=sessions or MemorySessionStore(),
        call=call or _noop_call, extract=_extract,
        clock=clock or (lambda: 0.0), id_factory=_ids(),
        max_steps=5, session_ttl=300.0,
    )


@pytest.mark.asyncio
async def test_allow_then_finish_completes():
    proposer = _ScriptedProposer([
        Act(intention=Intention(capability="crowdsec.get_metrics", args={})),
        Finish(summary="fait"),
    ])
    policy = [Rule(match=Match(capability="crowdsec.get_metrics"), effect="allow")]
    res = await _loop(proposer, policy).handle("montre les métriques")
    assert isinstance(res, Completed)
    assert len(res.results) == 1


@pytest.mark.asyncio
async def test_deny_stops():
    proposer = _ScriptedProposer(
        [Act(intention=Intention(capability="crowdsec.get_metrics", args={}))]
    )
    res = await _loop(proposer, []).handle("x")  # politique vide → deny
    assert isinstance(res, Denied)


@pytest.mark.asyncio
async def test_approve_suspends_then_resume_completes():
    proposer = _ScriptedProposer([
        Act(intention=Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"})),
        Finish(summary="banni"),
    ])
    policy = [Rule(match=Match(capability="crowdsec.ban_ip"), effect="approve")]
    sessions = MemorySessionStore()
    loop = _loop(proposer, policy, sessions=sessions)
    res = await loop.handle("banni 203.0.113.9")
    assert isinstance(res, Suspended)
    loop._approvals.approve(res.approval_id, loop._approvals.get(res.approval_id).intention_hash)
    res2 = await loop.resume(res.approval_id)
    assert isinstance(res2, Completed)


@pytest.mark.asyncio
async def test_resume_expired_session_fails():
    proposer = _ScriptedProposer(
        [Act(intention=Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"}))]
    )
    policy = [Rule(match=Match(capability="crowdsec.ban_ip"), effect="approve")]
    clock_box = {"t": 0.0}
    loop = _loop(proposer, policy, clock=lambda: clock_box["t"])
    res = await loop.handle("banni 203.0.113.9")
    assert isinstance(res, Suspended)
    loop._approvals.approve(res.approval_id, loop._approvals.get(res.approval_id).intention_hash)
    clock_box["t"] = 10_000.0  # au-delà du TTL
    res2 = await loop.resume(res.approval_id)
    assert isinstance(res2, Failed)


@pytest.mark.asyncio
async def test_resume_preserves_results_across_suspension():
    # pas 1 : capacité `allow` exécutée immédiatement ; pas 2 : capacité `approve` → suspend
    proposer = _ScriptedProposer([
        Act(intention=Intention(capability="crowdsec.get_metrics", args={})),
        Act(intention=Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"})),
        Finish(summary="fait"),
    ])
    policy = [
        Rule(match=Match(capability="crowdsec.get_metrics"), effect="allow"),
        Rule(match=Match(capability="crowdsec.ban_ip"), effect="approve"),
    ]
    sessions = MemorySessionStore()
    loop = _loop(proposer, policy, sessions=sessions)
    res = await loop.handle("montre les métriques puis banni 203.0.113.9")
    assert isinstance(res, Suspended)
    loop._approvals.approve(res.approval_id, loop._approvals.get(res.approval_id).intention_hash)
    res2 = await loop.resume(res.approval_id)
    assert isinstance(res2, Completed)
    expected_steps = 2
    assert len(res2.results) == expected_steps  # le résultat du pas allow ne doit pas être perdu


@pytest.mark.asyncio
async def test_resume_twice_is_anti_replay_and_calls_agent_once():
    calls = {"n": 0}

    async def _counting_call(cap, args):
        calls["n"] += 1
        return {"ok": cap, "args": args}

    proposer = _ScriptedProposer([
        Act(intention=Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"})),
        Finish(summary="banni"),
    ])
    policy = [Rule(match=Match(capability="crowdsec.ban_ip"), effect="approve")]
    sessions = MemorySessionStore()
    loop = _loop(proposer, policy, sessions=sessions, call=_counting_call)
    res = await loop.handle("banni 203.0.113.9")
    assert isinstance(res, Suspended)
    loop._approvals.approve(res.approval_id, loop._approvals.get(res.approval_id).intention_hash)
    res2 = await loop.resume(res.approval_id)
    assert isinstance(res2, Completed)
    res3 = await loop.resume(res.approval_id)
    assert isinstance(res3, Failed)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_llm_never_sees_real_ip():
    seen = []

    class _Spy:
        async def propose(self, request_tokens, history):
            seen.append((request_tokens, tuple(history)))
            if len(seen) == 1:
                return Act(intention=Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"}))
            return Finish(summary="ok")

    policy = [Rule(match=Match(capability="crowdsec.ban_ip"), effect="allow")]

    async def _echo_call(cap, args):
        return {"echo_ip": args["ip"]}  # renvoie la vraie IP → doit être re-tokenisée

    res = await _loop(_Spy(), policy, call=_echo_call).handle("banni 203.0.113.9")
    assert isinstance(res, Completed)
    flat = json.dumps(seen, ensure_ascii=False)
    assert "203.0.113.9" not in flat  # ni requête ni observation ne fuit l'IP


@pytest.mark.asyncio
async def test_retokenize_uses_vault_even_when_extractor_misses_it():
    """B-1 : le vault connaît déjà la vraie IP (tokenisée à l'entrée de la requête).
    Même si l'extracteur (spaCy NER en prod) ne la redétecte pas dans le JSON du
    résultat d'exécution — cas réaliste : la NER ne "voit" pas toujours une IP noyée
    dans un blob JSON — la re-tokenisation doit rester complète et déterministe car
    elle se base sur ce que le vault connaît déjà, pas sur ce que l'extracteur trouve.
    Sans le fix, l'IP réelle fuite verbatim dans `history`, donc dans le prochain
    prompt envoyé au proposeur (LLM)."""
    calls = {"n": 0}

    def _flaky_extract(text):
        calls["n"] += 1
        if calls["n"] == 1:
            # 1er appel : tokenisation de la requête initiale, l'IP est détectée normalement.
            return {"IP": re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", text)}
        # Appels suivants (re-tokenisation du résultat JSON) : l'extracteur ne détecte rien.
        return {}

    seen_history: list[list[str]] = []

    class _Spy:
        async def propose(self, request_tokens, history):
            seen_history.append(list(history))
            if len(seen_history) == 1:
                return Act(intention=Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"}))
            return Finish(summary="ok")

    policy = [Rule(match=Match(capability="crowdsec.ban_ip"), effect="allow")]

    async def _echo_call(cap, args):
        return {"echo_ip": "203.0.113.9"}  # l'agent renvoie la vraie IP en clair

    loop = GatedLoop(
        proposer=_Spy(), catalog=_catalog(), policy=policy,
        sink=MemoryAuditSink(), approvals=ApprovalStore(), sessions=MemorySessionStore(),
        call=_echo_call, extract=_flaky_extract, clock=lambda: 0.0, id_factory=_ids(),
        max_steps=5, session_ttl=300.0,
    )
    res = await loop.handle("banni 203.0.113.9")
    assert isinstance(res, Completed)
    # 2e appel au proposeur : voit l'historique du pas 1 (le résultat re-tokenisé).
    second_call_history = json.dumps(seen_history[1], ensure_ascii=False)
    assert "203.0.113.9" not in second_call_history
    assert "IP_1" in second_call_history


@pytest.mark.asyncio
async def test_proposer_error_returns_failed_not_raised():
    """B-2 : l'épuisement du proposeur (LLM incapable de produire une proposition
    valide dans le budget d'essais) doit se traduire par un `Failed` terminal, pas
    par une exception non gérée remontant jusqu'à un 500 côté app."""
    class _ExplodingProposer:
        async def propose(self, request_tokens, history):
            raise ProposerError("budget d'essais épuisé")

    res = await _loop(_ExplodingProposer(), []).handle("x")
    assert isinstance(res, Failed)
