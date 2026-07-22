from agents.infer_wiring import build_infer_client, resolve_lora_models
from clients.openai_compat_client import OpenAICompatClient


def test_resolve_from_per_agent_var():
    env = {"CROWDSEC_LORA_MODEL": "crowdsec-lora"}
    assert resolve_lora_models(env)["crowdsec"] == "crowdsec-lora"


def test_resolve_from_global_map():
    env = {"AGENT_LORA_MODELS": "crowdsec=cs-lora,opnsense=op-lora"}
    m = resolve_lora_models(env)
    assert m["crowdsec"] == "cs-lora" and m["opnsense"] == "op-lora"


def test_per_agent_overrides_global():
    env = {"AGENT_LORA_MODELS": "crowdsec=global", "CROWDSEC_LORA_MODEL": "specifique"}
    assert resolve_lora_models(env)["crowdsec"] == "specifique"


def test_build_client_none_without_base_url():
    assert build_infer_client({}) is None


def test_build_client_when_base_url_set():
    client = build_infer_client({"AGENT_INFER_BASE_URL": "http://x/v1", "AGENT_INFER_API_KEY": "k"})
    assert isinstance(client, OpenAICompatClient)
