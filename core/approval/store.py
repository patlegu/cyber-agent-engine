"""Approbation humaine — fail-closed, liaison exacte intention↔autorisation.

Une approbation jamais résolue n'autorise rien (défaut pending → jamais exécuté).
Approuver produit une autorisation liée au HASH de l'intention précise montrée :
approuver X puis présenter une intention différente échoue (contre la substitution
de directive).
L'``id`` est fourni par l'appelant (pas d'horloge/aléa ici, pour garder ce module
pur et déterministe ; l'unicité est garantie par le serveur en amont).
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict

from core.policy.models import Intention

State = Literal["pending", "approved", "rejected", "expired"]


class ApprovalMismatch(Exception):
    """Le hash fourni ne correspond pas à l'intention approuvée."""


class ApprovalNotFound(Exception):
    """Approbation inconnue."""


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    intention: Intention
    intention_hash: str
    state: State = "pending"


def intention_hash(intention: Intention) -> str:
    """Hash canonique de l'intention : clés triées, insensible à l'ordre d'insertion des args."""
    canonical = json.dumps(intention.model_dump(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalStore:
    """Registre des approbations en attente. Un seul thread (asyncio coopératif)."""

    def __init__(self) -> None:
        self._by_id: dict[str, Approval] = {}
        self._seq = 0

    def create(self, intention: Intention, approval_id: str | None = None) -> Approval:
        if approval_id is None:
            self._seq += 1
            approval_id = f"appr-{self._seq}"
        ap = Approval(id=approval_id, intention=intention, intention_hash=intention_hash(intention))
        self._by_id[approval_id] = ap
        return ap

    def get(self, approval_id: str) -> Approval | None:
        return self._by_id.get(approval_id)

    def approve(self, approval_id: str, provided_hash: str) -> Approval:
        ap = self._require(approval_id)
        if provided_hash != ap.intention_hash:
            raise ApprovalMismatch(approval_id)
        updated = ap.model_copy(update={"state": "approved"})
        self._by_id[approval_id] = updated
        return updated

    def reject(self, approval_id: str) -> Approval:
        ap = self._require(approval_id)
        updated = ap.model_copy(update={"state": "rejected"})
        self._by_id[approval_id] = updated
        return updated

    def _require(self, approval_id: str) -> Approval:
        ap = self._by_id.get(approval_id)
        if ap is None:
            raise ApprovalNotFound(approval_id)
        return ap
