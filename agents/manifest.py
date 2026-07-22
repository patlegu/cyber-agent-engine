"""Manifestes de capacités déclarés — source de vérité du catalogue + conformance.

Le catalogue de politique se construit depuis ces déclarations (déterministe,
indépendant de la disponibilité des agents). Au démarrage, on vérifie que le
`get_capabilities()` live d'un agent correspond à sa déclaration (détection de
drift → refus de démarrer).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from core.policy.catalog import Capability

_MANIFEST_DIR = Path(__file__).parent / "manifests"


class ManifestConformanceError(Exception):
    """Le manifeste déclaré et les capacités live de l'agent divergent."""


def _declared(agent_name: str) -> dict[str, list[str]]:
    """Charge le manifeste YAML de l'agent et renvoie {fonction: required_args}."""
    path = _MANIFEST_DIR / f"{agent_name}.yml"
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {c["name"]: list(c.get("required_args", [])) for c in data["capabilities"]}


def load_manifest(agent_name: str) -> list[Capability]:
    """Charge le manifeste déclaré et renvoie des `Capability` namespacées `<agent>.<fn>`."""
    declared = _declared(agent_name)
    return [
        Capability(name=f"{agent_name}.{fn}", required_args=req) for fn, req in declared.items()
    ]


def _live_required(cap: dict[str, Any]) -> list[str]:
    """Extrait `required` d'une capacité live.

    `ToolAgent.get_capabilities()` renvoie un schéma function-calling où
    `required` est niché sous `parameters.required` ; on accepte aussi un
    `required` au premier niveau (forme simplifiée utilisée en test).
    """
    if "required" in cap:
        return list(cap["required"])
    return list(cap.get("parameters", {}).get("required", []))


def check_conformance(agent_name: str, live_caps: list[dict[str, Any]]) -> None:
    """Compare le manifeste déclaré aux capacités live de l'agent.

    Écart (fonction manquante/en trop, ou `required_args` différent) → refus
    (`ManifestConformanceError`), jamais un passage silencieux.
    """
    declared = _declared(agent_name)
    live = {c["name"]: sorted(_live_required(c)) for c in live_caps}
    declared_sorted = {fn: sorted(req) for fn, req in declared.items()}
    if live.keys() != declared_sorted.keys():
        missing = declared_sorted.keys() ^ live.keys()
        raise ManifestConformanceError(f"{agent_name}: fonctions divergentes {missing}")
    for fn, req in declared_sorted.items():
        if live[fn] != req:
            raise ManifestConformanceError(
                f"{agent_name}.{fn}: required déclaré {req} != live {live[fn]}"
            )
