import pytest

from core.execution.authorization import Authorized, NotAuthorized, grant
from core.execution.boundary import execute
from core.policy.models import Intention, Rule, Verdict
from core.tokens.vault import Vault, tokenize


def _extract(text: str) -> dict[str, list[str]]:
    return {"IP": [t for t in text.split() if t.count(".") == 3]}


def _allow(intention: Intention) -> Verdict:
    return Verdict(effect="allow", matched_rule=Rule.model_validate(
        {"match": {"capability": intention.capability}, "effect": "allow"}), intention=intention)


def test_authorized_infalsifiable() -> None:
    it = Intention(capability="crowdsec.add_ban", args={})
    with pytest.raises(TypeError):
        Authorized(it, object())  # sentinelle bidon -> refus


def test_grant_refuse_un_verdict_non_allow() -> None:
    it = Intention(capability="crowdsec.add_ban", args={})
    deny = Verdict(effect="deny", matched_rule=None, intention=it)
    with pytest.raises(NotAuthorized):
        grant(deny)


def test_grant_produit_un_authorized_pour_allow() -> None:
    it = Intention(capability="crowdsec.get_decisions", args={})
    assert isinstance(grant(_allow(it)), Authorized)


async def test_execute_detokenise_avant_l_appel() -> None:
    v = Vault()
    tok = tokenize("10.0.0.5", v, _extract)  # IP_1 -> 10.0.0.5
    it = Intention(capability="crowdsec.add_ban", args={"ip": tok})
    seen: dict[str, dict[str, str]] = {}

    async def call(capability: str, args: dict[str, str]) -> dict[str, str]:
        seen["args"] = args
        return {"status": "ok"}

    result = await execute(grant(_allow(it)), v, call)
    assert result == {"status": "ok"}
    assert seen["args"] == {"ip": "10.0.0.5"}  # détokenisé au dernier moment
