"""Journal d'audit — append-only, JETONS uniquement.

L'audit reçoit des données déjà tokenisées (l'invariant est vérifié par test de
propriété) : aucune valeur réelle ne doit y apparaître. Le puits mémoire sert au
dev/tests ; un puits fichier/OpenSearch viendra en exploitation (sous-projet D).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from core.policy.models import Verdict


class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event: str
    capability: str
    effect: str
    rule_reason: str | None
    args: dict[str, str]
    actor: str = "coordinator"


def entry_from_verdict(
    verdict: Verdict, event: str, actor: str = "coordinator", rule_reason: str | None = None
) -> AuditEntry:
    reason = rule_reason if rule_reason is not None else (
        verdict.matched_rule.reason if verdict.matched_rule else None
    )
    return AuditEntry(
        event=event,
        capability=verdict.intention.capability,
        effect=verdict.effect,
        rule_reason=reason,
        args=verdict.intention.args,
        actor=actor,
    )


class AuditSink(Protocol):
    def write(self, entry: AuditEntry) -> None: ...


class MemoryAuditSink:
    """Puits en mémoire (dev/tests). Append-only."""

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def write(self, entry: AuditEntry) -> None:
        self.entries.append(entry)
