# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frontière d'exécution : détokenise puis appelle l'agent-outil.

Seul endroit (avec la vue d'approbation humaine) où une valeur réelle réapparaît.
Prend un ``Authorized`` — pas une intention brute — donc rien n'atteint un
équipement sans être passé par la politique.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from core.execution.authorization import Authorized
from core.tokens.vault import Vault, detokenize

AgentCall = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]


async def execute(authorization: Authorized, vault: Vault, call: AgentCall) -> dict[str, Any]:
    real_args: dict[str, str] = detokenize(authorization.intention.args, vault)
    return await call(authorization.intention.capability, real_args)
