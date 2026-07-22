"""Preuve d'autorisation infalsifiable.

``execution.execute`` n'accepte QUE un ``Authorized``, que seuls ``grant`` (verdict
``allow``) ou ``grant_approved`` (approbation humaine résolue) peuvent produire.
Fabriquer un ``Authorized`` hors de ces fabriques est impossible (sentinelle privée)
— mypy et le runtime deviennent des gardiens de sécurité.
"""

from __future__ import annotations

from core.approval.store import Approval
from core.policy.models import Intention, Verdict

_GRANT = object()  # sentinelle privée au module


class NotAuthorized(Exception):
    """Tentative d'autoriser un verdict qui n'est pas ``allow``."""


class Authorized:
    """Intention prouvée autorisée. Ne peut être construite que par grant()/grant_approved()."""

    __slots__ = ("intention",)

    def __init__(self, intention: Intention, _grant: object) -> None:
        if _grant is not _GRANT:
            raise TypeError("Authorized ne peut être construit que par grant()/grant_approved()")
        self.intention = intention


def grant(verdict: Verdict) -> Authorized:
    if verdict.effect != "allow":
        raise NotAuthorized(verdict.effect)
    return Authorized(verdict.intention, _GRANT)


def _grant_intention(intention: Intention) -> Authorized:
    """Fabrique interne réservée au flux d'approbation."""
    return Authorized(intention, _GRANT)


def grant_approved(approval: Approval) -> Authorized:
    if approval.state != "approved":
        raise NotAuthorized(f"approbation {approval.id} en état {approval.state}")
    return _grant_intention(approval.intention)
