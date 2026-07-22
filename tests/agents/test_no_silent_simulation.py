import pytest

from agents.base import ToolAgent


class _Agent(ToolAgent):
    def __init__(self, **kw):
        super().__init__(tool_name="t", model_path=None, **kw)

    def _register_functions(self):
        return {"get_metrics": self._get_metrics}

    async def _get_metrics(self):
        return {"ok": True}


class _BrokenOllama:
    def chat(self, *a, **k):
        raise RuntimeError("ollama indisponible")


@pytest.mark.asyncio
async def test_ollama_error_does_not_silently_simulate():
    # execute() attrape l'exception -> ToolResult échec, PAS un résultat simulé.
    agent = _Agent(ollama_config={"model": "m", "url": "http://x"})
    agent.ollama_client = _BrokenOllama()
    res = await agent.execute("montre les métriques")
    assert res.success is False
    assert res.function != "get_metrics"  # rien n'a été « deviné » puis exécuté
