import pytest

from coordinator.agent_call import UnknownAgent, make_agent_call


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def execute_structured(self, function, args):
        self.calls.append((function, args))
        return {"success": True, "function": function, "args": args}


@pytest.mark.asyncio
async def test_splits_namespace_and_routes():
    fake = _FakeClient()
    call = make_agent_call({"crowdsec": fake})
    out = await call("crowdsec.ban_ip", {"ip": "203.0.113.9"})
    assert fake.calls == [("ban_ip", {"ip": "203.0.113.9"})]
    assert out["function"] == "ban_ip"


@pytest.mark.asyncio
async def test_unknown_agent_raises():
    call = make_agent_call({"crowdsec": _FakeClient()})
    with pytest.raises(UnknownAgent):
        await call("opnsense.add_nat", {})
