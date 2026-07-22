"""Puits d'audit durable — JSONL, jetons uniquement, rétention bornée optionnelle.

Implémente le Protocol ``AuditSink`` de ``core.audit.sink``. Chaque ``AuditEntry``
est écrite sur une ligne JSON. Sans rotation (``max_bytes=0``), append illimité.
Avec ``max_bytes>0``, rotation par taille via ``RotatingFileHandler`` (stdlib) :
le fichier tourne en ``.1``, ``.2``, … jusqu'à ``backup_count`` ; les plus vieux
sont supprimés → disque borné. Les entrées ne portent que des jetons (invariant
d'``AuditEntry``) — aucune valeur réelle n'atteint le fichier.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from core.audit.sink import AuditEntry


class FileAuditSink:
    """Écrit chaque entrée d'audit sur une ligne JSON, avec rotation optionnelle."""

    def __init__(self, path: str | Path, *, max_bytes: int = 0, backup_count: int = 0) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._logger: logging.Logger | None = None
        if max_bytes > 0:
            handler = logging.handlers.RotatingFileHandler(
                self._path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
            )
            logger = logging.getLogger(f"cyber_audit.{self._path}")
            logger.setLevel(logging.INFO)
            logger.propagate = False
            # Éviter les handlers dupliqués si un sink est recréé sur le même chemin.
            for existing in list(logger.handlers):
                logger.removeHandler(existing)
                existing.close()
            logger.addHandler(handler)
            self._logger = logger

    def write(self, entry: AuditEntry) -> None:
        line = entry.model_dump_json()
        if self._logger is not None:
            self._logger.info("%s", line)  # "%s" : pas de substitution du contenu JSON
        else:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
