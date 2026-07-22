"""Construction du catalogue de capacités + conformance au démarrage.

Le catalogue vient des manifestes DÉCLARÉS (déterministe). Pour chaque agent
joignable, on vérifie que son `get_capabilities()` live correspond à sa
déclaration ; un drift refuse le démarrage. Un agent injoignable n'invalide pas
le démarrage : ses capacités déclarées restent dans le catalogue (la politique
ne bouge pas), et un appel réel échouera proprement à l'exécution.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agents.manifest import check_conformance, load_manifest
from core.policy.catalog import Capability, CapabilityCatalog


async def build_catalog(
    agent_names: list[str],
    live_caps: Mapping[str, list[dict[str, Any]]],
) -> CapabilityCatalog:
    """Agrège les capacités déclarées et vérifie la conformance des agents joignables.

    Pour chaque agent de `agent_names` : ses capacités déclarées (manifeste)
    entrent toujours dans le catalogue. S'il est présent dans `live_caps`
    (donc joignable), son `get_capabilities()` live est comparé au manifeste ;
    un écart lève `ManifestConformanceError` et refuse le démarrage.
    """
    caps: list[Capability] = []
    for name in agent_names:
        caps.extend(load_manifest(name))
        if name in live_caps:
            check_conformance(name, live_caps[name])  # lève ManifestConformanceError sur drift
    return CapabilityCatalog(caps)
