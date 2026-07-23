# SPDX-License-Identifier: AGPL-3.0-or-later
"""Évaluateur de politique — fonction pure, déterministe, défaut fail-closed.

Confronte une ``Intention`` proposée par le LLM à la liste de règles de
l'opérateur et rend un ``Verdict``. Première règle qui matche gagne (l'ordre EST
la priorité, comme un firewall) ; aucune règle ne matche → ``deny``. Le LLM ne
peut pas s'auto-autoriser : seuls ``capability`` et ``args`` sont regardés,
jamais ``rationale``. Les conditions comparent des structures (glob + eq/ne/
in/nin/present/absent), sans aucune exécution de code.
"""

from __future__ import annotations

from fnmatch import fnmatchcase

from core.policy.models import ArgMatch, Intention, Match, Rule, Verdict


def _arg_matches(name: str, cond: ArgMatch, args: dict[str, str]) -> bool:  # noqa: PLR0911
    val = args.get(name)
    if cond.op == "present":
        return val is not None
    if cond.op == "absent":
        return val is None
    if val is None:
        return False  # eq/ne/in/nin sur un arg absent : ne matche pas
    if cond.op == "eq":
        return val == cond.value
    if cond.op == "ne":
        return val != cond.value
    if cond.op == "in":
        return isinstance(cond.value, list) and val in cond.value
    if cond.op == "nin":
        return isinstance(cond.value, list) and val not in cond.value
    return False  # pragma: no cover - op est un Literal exhaustif


def _match_applies(match: Match, intention: Intention) -> bool:
    if not fnmatchcase(intention.capability, match.capability):
        return False
    return all(_arg_matches(name, cond, intention.args) for name, cond in match.args.items())


def evaluate(intention: Intention, policy: list[Rule]) -> Verdict:
    """Confronte l'intention à la politique. Défaut deny (fail-closed)."""
    for rule in policy:
        if _match_applies(rule.match, intention):
            return Verdict(effect=rule.effect, matched_rule=rule, intention=intention)
    return Verdict(effect="deny", matched_rule=None, intention=intention)
