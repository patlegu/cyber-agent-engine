"""Tokenisation réversible des valeurs sensibles, liée à la session.

Le LLM et les logs ne voient QUE des jetons (``IP_1``, ``VPN_USER_2``). La table
jeton→valeur (le ``vault``) reste côté serveur et n'est jamais sérialisée hors de
celui-ci. La détokenisation n'a lieu qu'au tout dernier moment (cf. ``execution/``)
ou dans la vue d'approbation humaine.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

ExtractFn = Callable[[str], dict[str, list[str]]]


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

    def items(self) -> dict[str, str]:
        """Copie de la table jeton→valeur émise dans cette session."""
        return dict(self._to_real)

    def snapshot(self) -> dict[str, Any]:
        """État sérialisable du vault (pour persistance de session)."""
        return {"to_real": dict(self._to_real), "counters": dict(self._counters)}

    @classmethod
    def restore(cls, snap: dict[str, Any]) -> Vault:
        """Reconstruit un vault depuis un ``snapshot()`` : bijection et compteurs repris."""
        v = cls()
        v._to_real = dict(snap.get("to_real", {}))
        v._to_token = {real: tok for tok, real in v._to_real.items()}
        v._counters = dict(snap.get("counters", {}))
        return v


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
    """Remplace récursivement les jetons ÉMIS par le vault par leurs valeurs réelles.

    On ne remplace que les jetons que ce vault a effectivement produits (pas de
    reconnaissance par forme) : rien qui ressemble à un jeton mais n'a pas été émis
    n'est jamais touché. Remplacement du jeton le plus long au plus court pour qu'un
    jeton préfixe d'un autre (IP_1 vs IP_10) ne soit pas corrompu.
    """
    if isinstance(obj, str):
        text = obj
        for token, real in sorted(vault.items().items(), key=lambda kv: len(kv[0]), reverse=True):
            text = text.replace(token, real)
        return text
    if isinstance(obj, dict):
        return {k: detokenize(v, vault) for k, v in obj.items()}
    if isinstance(obj, list):
        return [detokenize(v, vault) for v in obj]
    return obj
