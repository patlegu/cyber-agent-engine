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
from coordinator.proposer import Finish, Proposal
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
            self._sink.write(entry_from_verdict(verdict, event="resume_refuse"))
            return Denied(reason=f"approbation en état {approval.state}")
        result = await execute(authorized, vault, self._call)
        self._approvals.mark_executed(approval_id)
        self._sessions.delete(approval_id)
        self._sink.write(entry_from_verdict(verdict, event="executed_after_approval"))
        history = [*session.history, self._retokenize(result, vault)]
        return await self._run(vault, session.request_tokens, history, session.step + 1, [result])

    def reject(self, approval_id: str) -> LoopResult:
        """Rejette une approbation en attente : purge la session, aucune exécution."""
        approval = self._approvals.get(approval_id)
        if approval is None:
            return Failed(reason="approbation inconnue")
        self._approvals.reject(approval_id)
        self._sessions.delete(approval_id)
        verdict = Verdict(effect="approve", matched_rule=None, intention=approval.intention)
        self._sink.write(entry_from_verdict(verdict, event="rejected"))
        return Denied(reason="rejeté par l'opérateur")

    def _retokenize(self, result: dict[str, Any], vault: Vault) -> str:
        return tokenize(json.dumps(result, ensure_ascii=False), vault, self._extract)

    async def _run(
        self,
        vault: Vault,
        request_tokens: str,
        history: list[str],
        step: int,
        results: list[dict[str, Any]],
    ) -> LoopResult:
        while step < self._max_steps:
            proposal: Proposal = await self._proposer.propose(request_tokens, history)
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
                ))
                return Suspended(approval_id=sid)
            result = await execute(grant(verdict), vault, self._call)
            self._sink.write(entry_from_verdict(verdict, event="executed"))
            results.append(result)
            history = [*history, self._retokenize(result, vault)]
            step += 1
        return Failed(reason="nombre de pas maximal atteint")
