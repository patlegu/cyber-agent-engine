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


def decide(  # noqa: PLR0913 — tous mots-clés ; arg_meta est optionnel et rétrocompatible
    intention: Intention,
    *,
    catalog: CapabilityCatalog,
    policy: list[Rule],
    sink: AuditSink,
    arg_meta: dict[str, dict[str, str]] | None = None,
    event: str = "policy_decision",
) -> Verdict:
    """Valide l'intention (lève si capacité/args invalides), évalue, audite, renvoie.

    ``arg_meta`` fournit des pseudo-args synthétiques (ex. ``{"ip": {"scope":
    "private"}}``) qui n'existent QUE pour la durée de l'évaluation de politique :
    ils sont fusionnés dans une copie de ``args`` sous la forme ``f"{arg}__{k}"``
    et soumis à ``evaluate`` afin que les règles puissent matcher sur des méta-
    données de jeton (ex. ``ip__scope == private``) SANS que le moteur
    (``core/policy/engine.py``) n'ait besoin de connaître cette notion.

    Le ``Verdict`` renvoyé et l'entrée d'audit portent toujours l'intention
    ORIGINALE (sans clé synthétique) : ``catalog.validate_intention`` s'exécute
    sur l'originale (les pseudo-args ne sont pas de vrais args du catalogue), et
    aucune clé synthétique ne doit jamais fuiter vers l'audit ou l'exécution.
    """
    catalog.validate_intention(intention)
    if arg_meta:
        synthetic = {
            f"{arg}__{k}": v for arg, meta in arg_meta.items() for k, v in meta.items()
        }
        augmented = intention.model_copy(update={"args": {**intention.args, **synthetic}})
    else:
        augmented = intention
    raw = evaluate(augmented, policy)
    # Le verdict/l'audit portent l'intention ORIGINALE : aucune clé synthétique.
    verdict = Verdict(effect=raw.effect, matched_rule=raw.matched_rule, intention=intention)
    sink.write(entry_from_verdict(verdict, event=event))
    return verdict


__all__ = ["decide"]
