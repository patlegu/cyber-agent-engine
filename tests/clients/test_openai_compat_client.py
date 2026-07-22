import httpx
import pytest

from clients.openai_compat_client import OpenAICompatClient


@pytest.mark.asyncio
async def test_chat_posts_and_extracts_content():
    captured = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "HELLO"}}]})

    transport = httpx.MockTransport(_handler)
    client = OpenAICompatClient(base_url="http://x/v1", api_key="k")
    client._client = httpx.AsyncClient(transport=transport, base_url="http://x/v1")
    out = await client.chat([{"role": "user", "content": "hi"}], model="crowdsec-lora")
    assert out == "HELLO"
    assert captured["json"]["model"] == "crowdsec-lora"
    assert captured["url"].endswith("/chat/completions")
