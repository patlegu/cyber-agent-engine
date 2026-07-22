from typing import Literal

import pytest

from agents.coercion import CoercionError, coerce_args


async def _f(decision_id: int, force: bool = False,
             scope: Literal["ip", "range"] = "ip",
             ip: str = "", limit: int | None = None):
    ...


def test_coerces_declared_types():
    out = coerce_args(_f, {"decision_id": "123", "force": "true",
                           "scope": "range", "ip": "203.0.113.9", "limit": "50"})
    assert out == {"decision_id": 123, "force": True, "scope": "range",
                   "ip": "203.0.113.9", "limit": 50}


def test_bad_int_rejected():
    with pytest.raises(CoercionError):
        coerce_args(_f, {"decision_id": "abc"})


def test_literal_out_of_domain_rejected():
    with pytest.raises(CoercionError):
        coerce_args(_f, {"decision_id": "1", "scope": "country"})


def test_unknown_arg_passthrough():
    # arg non déclaré par func : laissé tel quel (le dispatch le rejettera si besoin)
    assert coerce_args(_f, {"decision_id": "1", "extra": "x"})["extra"] == "x"


def test_literal_int_members_return_typed():
    def g(level: Literal[1, 2, 3] = 1):
        pass
    out = coerce_args(g, {"level": "2"})
    assert out["level"] == 2  # noqa: PLR2004
    assert isinstance(out["level"], int)


def test_literal_int_out_of_domain():
    def g(level: Literal[1, 2, 3] = 1):
        pass
    with pytest.raises(CoercionError):
        coerce_args(g, {"level": "5"})
