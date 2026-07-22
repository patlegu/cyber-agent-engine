import pytest

from core.approval.store import (
    Approval,
    ApprovalMismatch,
    ApprovalStore,
    intention_hash,
)
from core.execution.authorization import Authorized, NotAuthorized, grant_approved
from core.policy.models import Intention


def _it(cap: str = "opnsense.add_nat", **args: str) -> Intention:
    return Intention(capability=cap, args=dict(args))


def test_hash_stable_et_sensible() -> None:
    a, b = _it(interface="wan"), _it(interface="wan")
    assert intention_hash(a) == intention_hash(b)
    assert intention_hash(a) != intention_hash(_it(interface="lan"))


def test_creation_est_pending() -> None:
    ap = ApprovalStore().create(_it())
    assert ap.state == "pending"


def test_approve_lie_au_hash_exact() -> None:
    store = ApprovalStore()
    ap = store.create(_it(interface="wan"))
    with pytest.raises(ApprovalMismatch):
        store.approve(ap.id, "hash_qui_ne_correspond_pas")
    ok = store.approve(ap.id, ap.intention_hash)
    assert ok.state == "approved"


def test_grant_approved_seulement_si_approuve() -> None:
    store = ApprovalStore()
    ap = store.create(_it())
    with pytest.raises(NotAuthorized):
        grant_approved(ap)  # encore pending
    approved = store.approve(ap.id, ap.intention_hash)
    assert isinstance(grant_approved(approved), Authorized)


def test_reject_bloque_l_autorisation() -> None:
    store = ApprovalStore()
    ap = store.reject(store.create(_it()).id)
    assert ap.state == "rejected"
    with pytest.raises(NotAuthorized):
        grant_approved(ap)
