"""Types de la couche politique — données pures, aucune logique d'I/O.

Une ``Rule`` est un artefact que l'opérateur écrit et versionne. ``evaluate``
(cf. engine.py) confronte une ``Intention`` proposée par le LLM à la liste de
règles et rend un ``Verdict``. Les conditions ne comparent que des structures
(glob, égalité, appartenance, présence) — jamais d'exécution de code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Effect = Literal["allow", "approve", "deny"]
Op = Literal["eq", "ne", "in", "nin", "present", "absent"]


class Intention(BaseModel):
    """Ce que le LLM PROPOSE — jamais ce qu'il exécute. ``args`` déjà tokenisés."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: str = Field(..., description="namespace.fonction, ex. opnsense.add_nat")
    args: dict[str, str] = Field(default_factory=dict)
    rationale: str = Field(
        "", description="Justification LLM — audit seulement, JAMAIS décisionnelle."
    )


class ArgMatch(BaseModel):
    """Condition structurelle sur un argument. ``value`` selon l'``op``."""

    model_config = ConfigDict(extra="forbid")

    op: Op
    value: str | list[str] | None = None


class Match(BaseModel):
    """Motif de sélection : glob sur la capacité + conditions sur les args."""

    model_config = ConfigDict(extra="forbid")

    capability: str = Field(..., description="Glob fnmatch, ex. opnsense.add_*")
    args: dict[str, ArgMatch] = Field(default_factory=dict)


class Rule(BaseModel):
    """Une règle de politique : si ``match`` s'applique, appliquer ``effect``."""

    model_config = ConfigDict(extra="forbid")

    match: Match
    effect: Effect
    reason: str = ""


class Verdict(BaseModel):
    """Résultat de ``evaluate`` : l'effet, la règle déclenchante, l'intention."""

    model_config = ConfigDict(extra="forbid")

    effect: Effect
    matched_rule: Rule | None
    intention: Intention
