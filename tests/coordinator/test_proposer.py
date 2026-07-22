import json

import pytest

from coordinator.proposer import Act, Finish, LlmProposer, ProposerError
from core.policy.catalog import Capability, CapabilityCatalog

_EXPECTED_ATTEMPTS = 3


class _ScriptedLLM:
    def __init__(self, replies):
        self._replies = list(replies)
        self.seen = []

    async def chat(self, messages, max_tokens=1024):
        self.seen.append(messages)
        return self._replies.pop(0)


def _catalog():
    return CapabilityCatalog([Capability(name="crowdsec.ban_ip", required_args=["ip"])])


@pytest.mark.asyncio
async def test_parses_action():
    reply = json.dumps({"action": {"capability": "crowdsec.ban_ip", "args": {"ip": "IP_1"}}})
    llm = _ScriptedLLM([reply])
    p = LlmProposer(llm=llm, catalog=_catalog())
    prop = await p.propose("banni IP_1", [])
    assert isinstance(prop, Act)
    assert prop.intention.capability == "crowdsec.ban_ip"
    assert prop.intention.args == {"ip": "IP_1"}


@pytest.mark.asyncio
async def test_parses_finish():
    llm = _ScriptedLLM([json.dumps({"final": "terminé"})])
    p = LlmProposer(llm=llm, catalog=_catalog())
    prop = await p.propose("rien", [])
    assert isinstance(prop, Finish)
    assert prop.summary == "terminé"


@pytest.mark.asyncio
async def test_retries_on_invalid_then_succeeds():
    llm = _ScriptedLLM([
        "pas du json",
        json.dumps({"action": {"capability": "crowdsec.unknown", "args": {}}}),
        json.dumps({"action": {"capability": "crowdsec.ban_ip", "args": {"ip": "IP_1"}}}),
    ])
    p = LlmProposer(llm=llm, catalog=_catalog(), max_retries=2)
    prop = await p.propose("banni IP_1", [])
    assert isinstance(prop, Act)
    assert len(llm.seen) == _EXPECTED_ATTEMPTS


@pytest.mark.asyncio
async def test_exhausts_retries():
    llm = _ScriptedLLM(["nope", "nope", "nope"])
    p = LlmProposer(llm=llm, catalog=_catalog(), max_retries=2)
    with pytest.raises(ProposerError):
        await p.propose("x", [])
