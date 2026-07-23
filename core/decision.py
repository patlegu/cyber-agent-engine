# SPDX-License-Identifier: AGPL-3.0-or-later
"""Séquence de décision partagée : valider → évaluer → auditer → verdict.

Extraite pour que l'orchestrateur mono-action ET la boucle ReAct gatée du
coordinateur partagent exactement la même logique (DRY), sans dupliquer l'ordre
validation/évaluation/audit.
"""

from __future__ import annotations

from core.audit.sink import AuditSink, entry_from_verdict
from core.policy.catalog import CapabilityCatalog
from core.policy.engine import evaluate
from core.policy.models import Intention, Rule, Verdict


def decide(
    intention: Intention,
    *,
    catalog: CapabilityCatalog,
    policy: list[Rule],
    sink: AuditSink,
    event: str = "policy_decision",
) -> Verdict:
    """Valide l'intention (lève si capacité/args invalides), évalue, audite, renvoie."""
    catalog.validate_intention(intention)
    verdict = evaluate(intention, policy)
    sink.write(entry_from_verdict(verdict, event=event))
    return verdict


__all__ = ["decide"]
