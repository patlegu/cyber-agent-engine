"""Tokenisation réversible des valeurs sensibles, liée à la session.

Le LLM et les logs ne voient QUE des jetons (``IP_1``, ``VPN_USER_2``). La table
jeton→valeur (le ``vault``) reste côté serveur et n'est jamais sérialisée hors de
celui-ci. La détokenisation n'a lieu qu'au tout dernier moment (cf. ``execution/``)
ou dans la vue d'approbation humaine.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

ExtractFn = Callable[[str], dict[str, list[str]]]

# Forme d'un jeton produit par ``Vault.token_for`` : LABEL_N (ex. IP_1,
# VPN_USER_2). Utilisé par ``detokenize`` pour repérer les jetons imbriqués
# dans une chaîne plus large (ex. "ban IP_1") sans avoir à énumérer le vault.
_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_\d+\b")


class Vault:
    """Bijection jeton↔valeur pour UNE session. Aucun état partagé entre sessions."""

    def __init__(self) -> None:
        self._to_real: dict[str, str] = {}
        self._to_token: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def token_for(self, label: str, value: str) -> str:
        existing = self._to_token.get(value)
        if existing is not None:
            return existing
        self._counters[label] = self._counters.get(label, 0) + 1
        token = f"{label}_{self._counters[label]}"
        self._to_real[token] = value
        self._to_token[value] = token
        return token

    def resolve(self, token: str) -> str | None:
        return self._to_real.get(token)

    def values(self) -> set[str]:
        return set(self._to_real.values())


def tokenize(text: str, vault: Vault, extract: ExtractFn) -> str:
    """Remplace chaque entité sensible détectée par son jeton stable de session."""
    entities = extract(text)
    # Remplacement par longueur décroissante : évite qu'une valeur sous-chaîne
    # d'une autre soit remplacée en premier.
    pairs: list[tuple[str, str]] = []
    for label, values in entities.items():
        for value in values:
            if value:
                pairs.append((label, value))
    for label, value in sorted(pairs, key=lambda p: len(p[1]), reverse=True):
        text = text.replace(value, vault.token_for(label, value))
    return text


def detokenize(obj: Any, vault: Vault) -> Any:
    """Remplace récursivement les jetons par leurs valeurs réelles (str/dict/list)."""
    if isinstance(obj, str):
        def _resolve_match(match: re.Match[str]) -> str:
            real = vault.resolve(match.group(0))
            return real if real is not None else match.group(0)

        return _TOKEN_RE.sub(_resolve_match, obj)
    if isinstance(obj, dict):
        return {k: detokenize(v, vault) for k, v in obj.items()}
    if isinstance(obj, list):
        return [detokenize(v, vault) for v in obj]
    return obj
