import pytest

from agents.base import FunctionCall, NoInferenceBackend, ToolAgent


class _Agent(ToolAgent):
    def __init__(self, **kw):
        super().__init__(tool_name="t", model_path=None, **kw)

    def _register_functions(self):
        return {"get_metrics": self._get_metrics}

    async def _get_metrics(self):
        return {"ok": True}


class _FakeOpenAI:
    def __init__(self):
        self.calls = []

    async def chat(self, messages, model, max_tokens=256):
        self.calls.append((model, messages))
        return '[{"name": "get_metrics", "arguments": "{}"}]'


@pytest.mark.asyncio
async def test_openai_backend_selected_and_used():
    fake = _FakeOpenAI()
    agent = _Agent(openai_client=fake, lora_model="crowdsec-lora")
    fc = await agent._infer_function("montre les métriques")
    assert isinstance(fc, FunctionCall)
    assert fake.calls and fake.calls[0][0] == "crowdsec-lora"
    assert fc.function == "get_metrics"


@pytest.mark.asyncio
async def test_no_backend_fails_closed():
    agent = _Agent()  # aucun backend d'inférence
    with pytest.raises(NoInferenceBackend):
        await agent._infer_function("montre les métriques")
