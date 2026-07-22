"""Puits d'audit durable — append-only JSONL, jetons uniquement.

Implémente le Protocol ``AuditSink`` de ``core.audit.sink`` pour l'exploitation.
Chaque ``AuditEntry`` est écrite sur une ligne JSON, en mode append. Les entrées
ne portent que des jetons (invariant de ``AuditEntry``) — aucune valeur réelle
n'atteint le fichier.
"""

from __future__ import annotations

from pathlib import Path

from core.audit.sink import AuditEntry


class FileAuditSink:
    """Écrit chaque entrée d'audit sur une ligne JSON, append-only."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, entry: AuditEntry) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(entry.model_dump_json() + "\n")
