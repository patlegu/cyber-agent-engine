"""Extracteur PII regex — déterministe, sans dépendance lourde.

Alimente la tokenisation du coordinateur : détecte les entités réseau sensibles
(IP, sous-réseau, MAC, hostname, port, CVE, hash) et les rend par label. Calibré
précision > rappel sur les types ambigus : on préfère ne pas sur-tokeniser le
bruit. Le matching le plus spécifique d'abord (CIDR avant IP nue) évite qu'un
sous-réseau ré-émette son IP.

Une variante spaCy (``NERExtractor``) reste disponible via l'extra [ner] pour le
NL riche, mais n'est pas câblée par défaut.
"""

from __future__ import annotations

import re

from core.tokens.vault import ExtractFn

_IPV4 = r"(?:\d{1,3}\.){3}\d{1,3}"
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("IP_SUBNET", re.compile(rf"\b{_IPV4}/\d{{1,2}}\b")),
    ("IP_ADDRESS", re.compile(rf"\b{_IPV4}\b")),
    ("MAC_ADDRESS", re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")),
    ("CVE", re.compile(r"\bCVE-\d{4}-\d{4,7}\b")),
    ("HASH", re.compile(r"\b(?:[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64})\b")),
    ("HOSTNAME", re.compile(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b")),
    ("PORT_NUMBER", re.compile(r"(?<=:)\d{2,5}\b")),
]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def build_regex_extractor() -> ExtractFn:
    """Renvoie un extracteur pur : texte → {label: [valeurs uniques, ordre stable]}."""

    def _extract(text: str) -> dict[str, list[str]]:
        # On masque au fur et à mesure les segments déjà capturés par un label plus
        # spécifique, pour qu'un CIDR ne soit pas ré-émis comme IP nue ni un FQDN
        # comme rien d'autre.
        remaining = text
        result: dict[str, list[str]] = {}
        for label, pattern in _PATTERNS:
            found = pattern.findall(remaining)
            result[label] = _dedupe(found)
            if found:
                remaining = pattern.sub(" ", remaining)
        return result

    return _extract
