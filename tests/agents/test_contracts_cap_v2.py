import pytest
from pydantic import ValidationError

from agents.contracts import AgentExecuteRequest


def test_structured_request_roundtrip():
    req = AgentExecuteRequest(function="ban_ip", args={"ip": "203.0.113.9"})
    assert req.function == "ban_ip"
    assert req.args == {"ip": "203.0.113.9"}


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        AgentExecuteRequest(function="ban_ip", args={}, entities={"IP": ["x"]})


def test_requires_command_or_function():
    with pytest.raises(ValidationError):
        AgentExecuteRequest(args={"ip": "x"})


def test_args_value_bound_rejected():
    with pytest.raises(ValidationError):
        AgentExecuteRequest(function="ban_ip", args={"ip": "x" * 8193})


def test_too_many_args_rejected():
    big = {f"k{i}": "v" for i in range(65)}
    with pytest.raises(ValidationError):
        AgentExecuteRequest(function="f", args=big)
