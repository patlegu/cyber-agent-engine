# SPDX-License-Identifier: AGPL-3.0-or-later
"""Persistance de session pour la boucle gatée — chiffrée au repos, à échéance.

Une session suspendue (verdict `approve`) contient le mapping jeton→valeur réelle
(PII) : elle est chiffrée sur disque (Fernet) et porte une échéance. Une session
expirée est purgée à la lecture (ses jetons disparaissent) — c'est la réponse à la
fuite de vault des approbations jamais résolues.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Field

Clock = Callable[[], float]


class SessionKeyNotConfigured(Exception):
    """Clé de chiffrement de session absente — le coordinateur ne doit pas démarrer."""


class SessionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    request_tokens: str
    vault_snapshot: dict[str, Any]
    history: list[str]
    step: int
    expires_at: float
    results: list[dict[str, Any]] = Field(default_factory=list)
    rule_reason: str | None = None


class SessionStore(Protocol):
    def save(self, state: SessionState) -> None: ...
    def get(self, session_id: str, *, now: float) -> SessionState | None: ...
    def delete(self, session_id: str) -> None: ...


class MemorySessionStore:
    """Store en mémoire — pour les tests, aucune persistance entre process."""

    def __init__(self) -> None:
        self._by_id: dict[str, SessionState] = {}

    def save(self, state: SessionState) -> None:
        self._by_id[state.id] = state

    def get(self, session_id: str, *, now: float) -> SessionState | None:
        state = self._by_id.get(session_id)
        if state is None:
            return None
        if state.expires_at <= now:
            self.delete(session_id)
            return None
        return state

    def delete(self, session_id: str) -> None:
        self._by_id.pop(session_id, None)


class EncryptedFileSessionStore:
    """Store sur disque, un fichier chiffré (Fernet) par session."""

    def __init__(self, directory: Path, key: bytes) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(key)

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.session"

    def save(self, state: SessionState) -> None:
        blob = self._fernet.encrypt(state.model_dump_json().encode("utf-8"))
        self._path(state.id).write_bytes(blob)

    def get(self, session_id: str, *, now: float) -> SessionState | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        data = json.loads(self._fernet.decrypt(path.read_bytes()).decode("utf-8"))
        state = SessionState.model_validate(data)
        if state.expires_at <= now:
            self.delete(session_id)
            return None
        return state

    def delete(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)


def load_session_key(env: Mapping[str, str], var: str = "COORDINATOR_SESSION_KEY") -> bytes:
    """Charge la clé Fernet depuis l'environnement — fail-closed si absente."""
    raw = env.get(var, "")
    if not raw:
        raise SessionKeyNotConfigured(f"{var} absent : le coordinateur refuse de démarrer")
    return raw.encode("utf-8")
