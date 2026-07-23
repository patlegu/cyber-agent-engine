# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chargement et validation de la politique au démarrage.

Une politique invalide DOIT empêcher le démarrage plutôt que de dégrader en
silence : règle malformée (Pydantic) ou glob qui ne couvre aucune capacité
connue (typo de l'opérateur) → ``PolicyError``.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from pydantic import ValidationError

from core.policy.catalog import CapabilityCatalog
from core.policy.models import Rule


class PolicyError(Exception):
    """La politique fournie est invalide ; le serveur ne doit pas démarrer."""


def load_policy(raw_rules: list[dict[str, Any]], catalog: CapabilityCatalog) -> list[Rule]:
    rules: list[Rule] = []
    known = catalog.names()
    for i, raw in enumerate(raw_rules):
        try:
            rule = Rule.model_validate(raw)
        except ValidationError as exc:
            raise PolicyError(f"règle #{i} malformée : {exc}") from exc
        if not any(fnmatchcase(name, rule.match.capability) for name in known):
            raise PolicyError(
                f"règle #{i} : le glob '{rule.match.capability}' ne couvre aucune capacité connue"
            )
        rules.append(rule)
    return rules
