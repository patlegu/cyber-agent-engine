import pytest

from agents.base import ToolAgent


class _FakeAgent(ToolAgent):
    def __init__(self):
        super().__init__(tool_name="fake", model_path=None)

    def _register_functions(self):
        return {"del_dec": self._del_dec}

    async def _del_dec(self, decision_id: int) -> dict:
        return {"deleted": decision_id, "type": type(decision_id).__name__}


@pytest.mark.asyncio
async def test_execute_direct_coerces_int():
    agent = _FakeAgent()
    res = await agent.execute_direct("del_dec", {"decision_id": "42"})
    assert res.success is True
    assert res.result == {"deleted": 42, "type": "int"}


@pytest.mark.asyncio
async def test_execute_direct_bad_coercion_fails_closed():
    agent = _FakeAgent()
    res = await agent.execute_direct("del_dec", {"decision_id": "abc"})
    assert res.success is False
    assert res.error_code is not None
