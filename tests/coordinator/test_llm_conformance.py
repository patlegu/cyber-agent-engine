"""Conformité de `CoordinatorLLM` au Protocol `ChatLLM` du proposeur (sous-projet B)."""

import inspect

from coordinator.llm.coordinator_llm import CoordinatorLLM
from coordinator.proposer import ChatLLM


def test_coordinator_llm_is_chatllm():
    # __init__ ne fait aucune I/O réseau (backend initialisé seulement dans init()).
    assert isinstance(CoordinatorLLM(), ChatLLM)


def test_chat_signature_matches_protocol():
    sig = inspect.signature(CoordinatorLLM.chat)
    params = list(sig.parameters)
    assert params[0] == "self" and "messages" in params and "max_tokens" in params
    assert inspect.iscoroutinefunction(CoordinatorLLM.chat)
