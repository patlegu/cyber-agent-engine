"""Test de l'endpoint /health du serveur d'agent.

La sonde de santé /health est non authentifiée pour permettre au coordinator
et aux vérifications de conteneur (healthcheck, depends_on: service_healthy)
d'évaluer l'état du serveur sans clé API.
"""

import importlib

from fastapi.testclient import TestClient


def test_health_no_auth(monkeypatch):
    """Vérifie que /health est accessible sans authentification et retourne 200."""
    monkeypatch.setenv("AGENT_API_KEY", "secret")
    import server  # noqa: PLC0415 — import différé : ne doit s'exécuter qu'une fois la clé positionnée

    importlib.reload(server)
    # TestClient sans context-manager ne lance pas le lifespan (pas d'init d'agents).
    client = TestClient(server.app)
    r = client.get("/health")  # aucune clé fournie
    assert r.status_code == 200  # noqa: PLR2004
    assert r.json() == {"status": "ok"}
