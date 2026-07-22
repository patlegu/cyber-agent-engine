# tests/test_compose.py
import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent


def _compose() -> dict:
    return yaml.safe_load((_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_two_services_on_internal_network():
    c = _compose()
    assert set(("agent-server", "coordinator")).issubset(c["services"])
    assert c.get("networks")  # réseau défini


def test_agent_server_not_published_to_host():
    svc = _compose()["services"]["agent-server"]
    # pas de ports publiés sur l'hôte (isolé sur le réseau interne)
    assert "ports" not in svc or not svc["ports"]


def test_coordinator_publishes_and_depends_on_agent():
    svc = _compose()["services"]["coordinator"]
    assert svc.get("ports")  # exposé à l'opérateur
    assert "agent-server" in (svc.get("depends_on") or {})


def test_coordinator_healthcheck_and_persistence():
    c = _compose()
    coord = c["services"]["coordinator"]
    assert "healthcheck" in coord
    assert c.get("volumes")  # volumes nommés de persistance


def test_env_example_has_required_keys_no_secrets():
    env = (_ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ("COORDINATOR_API_KEY", "COORDINATOR_SESSION_KEY", "AGENT_API_KEY"):
        assert key in env
    # placeholders seulement : pas de valeur ressemblant à une vraie clé Fernet (44 chars b64)
    assert not re.search(r'=\s*[A-Za-z0-9_-]{40,}=*\s*$', env, re.MULTILINE)


def test_gitignore_excludes_env():
    assert ".env" in (_ROOT / ".gitignore").read_text(encoding="utf-8")


def test_coordinator_agent_key_wired():
    """La clé sortante du coordinateur (AGENT_SERVER_KEY) doit être câblée
    sur le même secret que celui appliqué par le serveur d'agents
    (AGENT_API_KEY), sinon le coordinateur envoie une clé vide et se
    prend un 401 au démarrage (crash-loop)."""
    svc = _compose()["services"]["coordinator"]
    env = svc.get("environment") or {}
    assert env.get("AGENT_SERVER_KEY") == "${AGENT_API_KEY}"


def test_coordinator_port_pinned():
    """Le port d'écoute du conteneur doit être figé à 8080 dans
    `environment` (qui prime sur `env_file`), sinon COORDINATOR_PORT
    venant de .env change le port d'écoute réel alors que le mapping
    `ports:` et le healthcheck restent câblés sur :8080."""
    svc = _compose()["services"]["coordinator"]
    env = svc.get("environment") or {}
    assert env.get("COORDINATOR_PORT") == "8080"
