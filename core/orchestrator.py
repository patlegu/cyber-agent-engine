"""Orchestrateur de confiance — le cœur mince qui compose les feuilles pures.

Flux : requête → tokenize → le LLM PROPOSE une intention → validation catalogue →
evaluate → { deny: stop | approve: suspend | allow: grant+execute } → audit.
Aucune valeur réelle ne quitte cette frontière vers le LLM ou l'audit ; seul
``execution.execute`` détokenise, au dernier moment.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from core.approval.store import ApprovalNotFound, ApprovalStore
from core.audit.sink import AuditSink, entry_from_verdict
from core.execution.authorization import NotAuthorized, grant, grant_approved
from core.execution.boundary import AgentCall, execute
from core.policy.catalog import CapabilityCatalog
from core.policy.engine import evaluate
from core.policy.models import Intention, Rule, Verdict
from core.tokens.vault import ExtractFn, Vault, tokenize

Status = Literal["executed", "denied", "pending_approval"]


class Proposer(Protocol):
    async def propose(self, prompt_tokenise: str) -> Intention: ...


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status
    verdict: Verdict
    approval_id: str | None = None
    result: dict[str, Any] | None = None


class TrustOrchestrator:
    def __init__(  # noqa: PLR0913 — racine de composition : câble les 7 feuilles pures
        self,
        *,
        policy: list[Rule],
        catalog: CapabilityCatalog,
        extract: ExtractFn,
        proposer: Proposer,
        call: AgentCall,
        sink: AuditSink,
        approvals: ApprovalStore,
    ) -> None:
        self._policy = policy
        self._catalog = catalog
        self._extract = extract
        self._proposer = proposer
        self._call = call
        self._sink = sink
        self._approvals = approvals
        # Un vault par session d'approbation en attente, pour détokeniser au resume.
        self._vaults: dict[str, Vault] = {}

    async def handle(self, request_text: str) -> Outcome:
        vault = Vault()
        prompt = tokenize(request_text, vault, self._extract)
        intention = await self._proposer.propose(prompt)
        self._catalog.validate_intention(intention)  # lève si capacité inconnue / args manquants
        verdict = evaluate(intention, self._policy)
        self._sink.write(entry_from_verdict(verdict, event="policy_decision"))

        if verdict.effect == "deny":
            return Outcome(status="denied", verdict=verdict)
        if verdict.effect == "approve":
            approval = self._approvals.create(intention)
            self._vaults[approval.id] = vault
            return Outcome(status="pending_approval", verdict=verdict, approval_id=approval.id)

        result = await execute(grant(verdict), vault, self._call)
        self._sink.write(entry_from_verdict(verdict, event="executed"))
        return Outcome(status="executed", verdict=verdict, result=result)

    async def resume(self, approval_id: str) -> Outcome:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise ApprovalNotFound(approval_id)
        verdict = Verdict(effect="approve", matched_rule=None, intention=approval.intention)
        try:
            # grant_approved lève si l'approbation n'est pas dans l'état "approved" (fail-closed).
            authorized = grant_approved(approval)
        except NotAuthorized:
            # Une tentative de reprise non autorisee (approbation pending/rejetee/expiree)
            # doit laisser une trace : l'audit est la propriete de securite centrale.
            self._sink.write(entry_from_verdict(verdict, event="resume_refuse"))
            raise
        vault = self._vaults.get(approval_id, Vault())  # get = vault conserve si execute echoue
        result = await execute(authorized, vault, self._call)
        # Consomme l'approbation seulement apres succes : un 2e resume est refuse fail-closed.
        self._approvals.mark_executed(approval_id)
        self._vaults.pop(approval_id, None)  # nettoyage du vault de session apres succes
        self._sink.write(entry_from_verdict(verdict, event="executed_after_approval"))
        return Outcome(status="executed", verdict=verdict, result=result)

    def reject(self, approval_id: str) -> Outcome:
        """Rejette une approbation en attente : audit + nettoyage du vault de session."""
        approval = self._approvals.reject(approval_id)  # leve ApprovalNotFound si inconnu
        verdict = Verdict(effect="approve", matched_rule=None, intention=approval.intention)
        self._sink.write(entry_from_verdict(verdict, event="rejected"))
        self._vaults.pop(approval_id, None)
        return Outcome(status="denied", verdict=verdict)


__all__ = ["Outcome", "Proposer", "Status", "TrustOrchestrator"]
