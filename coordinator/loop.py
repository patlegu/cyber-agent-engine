"""Boucle ReAct gatée — orchestrateur multi-pas du coordinateur.

Chaque pas : le Proposer propose (LLM → intention validée), `core.decide` rend un
verdict fail-closed. `deny` stoppe ; `approve` SUSPEND toute la boucle (session
persistée, à échéance) jusqu'à reprise humaine ; `allow` exécute via la frontière
`core.execution` puis re-tokenise le résultat pour le pas suivant. Le LLM ne voit
que des jetons.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from coordinator.agent_call import AgentCall
from coordinator.proposer import Finish, Proposal, ProposerError
from coordinator.session import Clock, SessionState, SessionStore
from core.approval.store import ApprovalStore
from core.audit.sink import AuditSink, entry_from_verdict
from core.decision import decide
from core.execution.authorization import NotAuthorized, grant, grant_approved
from core.execution.boundary import execute
from core.policy.catalog import CapabilityCatalog
from core.policy.models import Rule, Verdict
from core.tokens.vault import ExtractFn, Vault, tokenize


class ProposerLike(Protocol):
    async def propose(self, request_tokens: str, history: list[str]) -> Proposal: ...


class Completed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    results: list[dict[str, Any]]


class Suspended(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str


class Denied(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


class Failed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


LoopResult = Completed | Suspended | Denied | Failed


class GatedLoop:
    """Orchestre le cycle proposer → décider → (suspendre | exécuter) → re-tokeniser."""

    def __init__(  # noqa: PLR0913 — racine de composition de la boucle
        self,
        *,
        proposer: ProposerLike,
        catalog: CapabilityCatalog,
        policy: list[Rule],
        sink: AuditSink,
        approvals: ApprovalStore,
        sessions: SessionStore,
        call: AgentCall,
        extract: ExtractFn,
        clock: Clock,
        id_factory: Callable[[], str],
        max_steps: int = 10,
        session_ttl: float = 300.0,
    ) -> None:
        self._proposer = proposer
        self._catalog = catalog
        self._policy = policy
        self._sink = sink
        self._approvals = approvals
        self._sessions = sessions
        self._call = call
        self._extract = extract
        self._clock = clock
        self._new_id = id_factory
        self._max_steps = max_steps
        self._ttl = session_ttl

    async def handle(self, request_text: str) -> LoopResult:
        """Démarre une nouvelle boucle : tokenise la requête, exécute depuis le pas 0."""
        vault = Vault()
        request_tokens = tokenize(request_text, vault, self._extract)
        return await self._run(vault, request_tokens, history=[], step=0, results=[])

    async def resume(self, approval_id: str) -> LoopResult:
        """Reprend une boucle suspendue après décision humaine sur l'approbation."""
        session = self._sessions.get(approval_id, now=self._clock())
        if session is None:
            return Failed(reason="session inconnue ou expirée")
        approval = self._approvals.get(approval_id)
        if approval is None:
            return Failed(reason="approbation inconnue")
        verdict = Verdict(effect="approve", matched_rule=None, intention=approval.intention)
        vault = Vault.restore(session.vault_snapshot)
        try:
            authorized = grant_approved(approval)
        except NotAuthorized:
            self._sink.write(entry_from_verdict(
                verdict, event="resume_refuse", rule_reason=session.rule_reason
            ))
            return Denied(reason=f"approbation en état {approval.state}")
        # Consommer l'approbation AVANT d'exécuter : anti-rejeu fail-closed. Une panne
        # transitoire de l'agent pendant `execute` ne doit jamais laisser une session
        # approuvée rejouable (un ban n'est pas idempotent, il ne doit jamais s'exécuter deux fois).
        self._approvals.mark_executed(approval_id)
        self._sessions.delete(approval_id)
        try:
            result = await execute(authorized, vault, self._call)
        except Exception as exc:  # frontière d'exécution : jamais de 500 non géré
            return Failed(reason=f"execution: {type(exc).__name__}")
        self._sink.write(entry_from_verdict(
            verdict, event="executed_after_approval", rule_reason=session.rule_reason
        ))
        history = [*session.history, self._retokenize(result, vault)]
        results = [*session.results, result]
        return await self._run(vault, session.request_tokens, history, session.step + 1, results)

    def reject(self, approval_id: str) -> LoopResult:
        """Rejette une approbation en attente : purge la session, aucune exécution."""
        approval = self._approvals.get(approval_id)
        if approval is None:
            return Failed(reason="approbation inconnue")
        session = self._sessions.get(approval_id, now=self._clock())
        rule_reason = session.rule_reason if session is not None else None
        self._approvals.reject(approval_id)
        self._sessions.delete(approval_id)
        verdict = Verdict(effect="approve", matched_rule=None, intention=approval.intention)
        self._sink.write(entry_from_verdict(verdict, event="rejected", rule_reason=rule_reason))
        return Denied(reason="rejeté par l'opérateur")

    def _retokenize(self, result: dict[str, Any], vault: Vault) -> str:
        """Jetonise le résultat : d'abord les valeurs déjà connues du vault (déterministe,
        indépendant de l'extracteur), puis les entités nouvelles via l'extracteur.

        `tokenize` seul ne jetonise que ce que l'extracteur DÉTECTE — en prod, une NER
        spaCy qui échoue à re-détecter une IP déjà connue dans le JSON du résultat
        la laisserait fuiter verbatim dans `history`, donc dans le prochain prompt.
        Le coordinateur connaît déjà toutes les valeurs réelles du vault : la
        re-tokenisation doit être complète pour elles quel que soit l'extracteur.
        """
        text = json.dumps(result, ensure_ascii=False)
        for token, real in sorted(vault.items().items(), key=lambda kv: len(kv[1]), reverse=True):
            text = text.replace(real, token)
        return tokenize(text, vault, self._extract)

    async def _run(
        self,
        vault: Vault,
        request_tokens: str,
        history: list[str],
        step: int,
        results: list[dict[str, Any]],
    ) -> LoopResult:
        """Boucle proposer → décider → (suspendre | exécuter) jusqu'à `Finish` ou la limite."""
        while step < self._max_steps:
            try:
                proposal: Proposal = await self._proposer.propose(request_tokens, history)
            except ProposerError as exc:
                return Failed(reason=f"proposer: {type(exc).__name__}")
            if isinstance(proposal, Finish):
                return Completed(summary=proposal.summary, results=results)
            intention = proposal.intention
            verdict = decide(
                intention, catalog=self._catalog, policy=self._policy, sink=self._sink
            )
            if verdict.effect == "deny":
                return Denied(reason=f"politique: {intention.capability}")
            if verdict.effect == "approve":
                sid = self._new_id()
                self._approvals.create(intention, approval_id=sid)
                self._sessions.save(SessionState(
                    id=sid, request_tokens=request_tokens, vault_snapshot=vault.snapshot(),
                    history=history, step=step, expires_at=self._clock() + self._ttl,
                    results=results,
                    rule_reason=(verdict.matched_rule.reason if verdict.matched_rule else None),
                ))
                return Suspended(approval_id=sid)
            try:
                result = await execute(grant(verdict), vault, self._call)
            except Exception as exc:  # frontière d'exécution : jamais de 500 non géré
                return Failed(reason=f"execution: {type(exc).__name__}")
            self._sink.write(entry_from_verdict(verdict, event="executed"))
            results.append(result)
            history = [*history, self._retokenize(result, vault)]
            step += 1
        return Failed(reason="nombre de pas maximal atteint")
