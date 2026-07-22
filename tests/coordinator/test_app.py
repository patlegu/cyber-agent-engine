import itertools

from fastapi import status
from fastapi.testclient import TestClient

from coordinator.app import build_app
from coordinator.loop import GatedLoop
from coordinator.proposer import Act, Finish
from coordinator.session import MemorySessionStore
from core.approval.store import ApprovalStore
from core.audit.sink import MemoryAuditSink
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import Intention, Match, Rule


class _Proposer:
    def __init__(self, seq):
        self._it = iter(seq)

    async def propose(self, request_tokens, history):
        return next(self._it)


def _ids():
    counter = itertools.count(1)
    return lambda: f"a{next(counter)}"


def _loop(seq, policy):
    async def _call(cap, args):
        return {"ok": cap}
    return GatedLoop(
        proposer=_Proposer(seq),
        catalog=CapabilityCatalog([Capability(name="crowdsec.get_metrics", required_args=[])]),
        policy=policy, sink=MemoryAuditSink(), approvals=ApprovalStore(),
        sessions=MemorySessionStore(), call=_call, extract=lambda t: {},
        clock=lambda: 0.0, id_factory=_ids(),
    )


def _client(loop):
    return TestClient(build_app(loop=loop, auth_secret="secret"))


def test_execute_requires_auth():
    loop = _loop([Finish(summary="x")], [])
    r = _client(loop).post("/coordinator/execute", json={"request": "hello"})
    assert r.status_code == status.HTTP_401_UNAUTHORIZED


def test_execute_completes_with_auth():
    seq = [
        Act(intention=Intention(capability="crowdsec.get_metrics", args={})),
        Finish(summary="fini"),
    ]
    policy = [Rule(match=Match(capability="crowdsec.get_metrics"), effect="allow")]
    r = _client(_loop(seq, policy)).post(
        "/coordinator/execute", headers={"X-API-Key": "secret"}, json={"request": "métriques"}
    )
    assert r.status_code == status.HTTP_200_OK
    assert r.json()["status"] == "completed"


def test_health_no_auth():
    r = _client(_loop([Finish(summary="x")], [])).get("/coordinator/health")
    assert r.status_code == status.HTTP_200_OK
