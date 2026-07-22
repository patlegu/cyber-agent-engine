"""Tests du serveur d'agent : auth fail-closed + suppression de la branche CAP v1.

Contexte environnement de test : `conftest.py` (racine, non modifiable ici) mock
`factory` et `factory.clients` en style *attribut* (`from factory.clients import X`,
utilisé par `agents/*.py`). `server.py` a besoin en plus d'un import de
sous-module dédié (`from factory.clients.native_vllm_client import
NativeVLLMClient`) que ce mock ne couvre pas (pas de `__path__` réel sur le
module mocké). On complète localement ici, sans toucher au conftest racine.

Par ailleurs, sans le protocole context manager (`with TestClient(...) as c`),
Starlette ne déclenche pas le `lifespan` de l'application — le dict `agents`
du serveur reste vide. Faire tourner le vrai `lifespan` (instanciation réelle
des agents OPNsense/WireGuard/CrowdSec) se heurte au même problème de mock que
ci-dessus sur d'autres sous-modules `factory.clients.*` (`ollama_client`,
`pfsense_client`, ...), hors périmètre de cette tâche. Les tests qui ont besoin
d'un agent pour atteindre le dispatch peuplent donc `server.agents` eux-mêmes
avec un stub minimal, conformément à la piste de repli du brief de tâche.
"""

import importlib
import json
import sys
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agents.base import ToolResult
from core.auth.api_key import AuthNotConfigured

sys.modules.setdefault("factory.clients.native_vllm_client", MagicMock())


def _client(monkeypatch, key="secret"):
    """Recharge `server` avec `AGENT_API_KEY` positionnée et renvoie (module, TestClient)."""
    monkeypatch.setenv("AGENT_API_KEY", key)
    import server  # noqa: PLC0415 — import différé : ne doit s'exécuter qu'une fois la clé positionnée

    importlib.reload(server)
    return server, TestClient(server.app)


class _StubAgent:
    """Agent minimal : ne reconnaît jamais rien en mode naturel, mais répond en direct."""

    tool_name = "stub"

    async def execute_direct(self, function, args):
        return ToolResult(
            success=True, function=function, args=args, result={"stub": True}, tool_name="stub"
        )

    async def execute(self, command):
        return ToolResult(success=False, function="unknown", args={}, result=None, tool_name="stub")


def test_no_key_configured_refuses_start(monkeypatch):
    monkeypatch.delenv("AGENT_API_KEY", raising=False)
    # `import server` peut être un premier import (exécute le module, donc lève
    # directement) ou un import déjà en cache par un test précédent (auquel cas
    # c'est le `reload` qui force la ré-exécution et lève). Les deux cas sont
    # englobés pour ne pas dépendre de l'ordre d'exécution des tests.
    with pytest.raises(AuthNotConfigured, match="AGENT_API_KEY"):
        import server  # noqa: PLC0415 — import différé, cf. commentaire ci-dessus

        importlib.reload(server)  # load_auth_secret lève AuthNotConfigured


def test_structured_requires_auth(monkeypatch):
    _, client = _client(monkeypatch)
    unauthorized = 401
    r = client.post("/agent/execute", json={"function": "get_metrics", "args": {}})
    assert r.status_code == unauthorized


def test_cap_v1_directive_no_longer_dispatched(monkeypatch):
    server, client = _client(monkeypatch)
    # Le lifespan réel ne tourne pas ici (cf. docstring du module) : on stub
    # `agents` pour que le dispatch mode-naturel ait un agent à interroger,
    # quel que soit celui choisi par le classifieur.
    for name in ("opnsense", "wireguard", "crowdsec"):
        server.agents[name] = _StubAgent()

    # Un ancien paquet CAP v1 (command JSON avec entities) ne doit PAS être
    # exécuté structurellement : plus de fusion entities→args.
    leaked_ip = "203.0.113.9"
    directive_payload = {
        "directive": "ban_ip",
        "entities": {"IP_ADDRESS": [leaked_ip]},
        "args": {},
    }
    r = client.post(
        "/agent/execute",
        headers={"X-API-Key": "secret"},
        json={"command": json.dumps(directive_payload)},
    )
    # Soit 400 (aucun agent NL ne l'interprète en test), soit succès NL — mais
    # jamais un ban structuré silencieux depuis les entities.
    assert leaked_ip not in r.text or r.json().get("function") != "ban_ip"
