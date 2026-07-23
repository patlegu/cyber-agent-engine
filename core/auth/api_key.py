# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authentification par clé API — fail-closed au démarrage, dépendance globale.

Le serveur DOIT refuser de démarrer sans secret configuré (``load_auth_secret``
lève). La vérification est en temps constant. La dépendance FastAPI est destinée
à être appliquée GLOBALEMENT (à toutes les routes), pour qu'on ne puisse pas
oublier de protéger une route neuve.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable, Mapping

from fastapi import Header, HTTPException, status


class AuthNotConfigured(Exception):
    """Aucun secret d'auth configuré — le serveur ne doit pas démarrer."""


def load_auth_secret(env: Mapping[str, str], var: str = "COORDINATOR_API_KEY") -> str:
    secret = env.get(var, "")
    if not secret:
        raise AuthNotConfigured(
            f"{var} absent ou vide : le coordinateur refuse de démarrer sans authentification"
        )
    return secret


def verify(provided: str | None, expected: str) -> bool:
    if provided is None:
        return False
    return hmac.compare_digest(provided, expected)


def make_auth_dependency(expected: str) -> Callable[[str | None], None]:
    """Fabrique la dépendance FastAPI liée au secret chargé au démarrage."""

    def _require(x_api_key: str | None = Header(default=None)) -> None:
        if not verify(x_api_key, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="clé API invalide ou absente"
            )

    return _require
