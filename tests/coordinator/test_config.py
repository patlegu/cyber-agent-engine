"""Tests de chargement de configuration du coordinateur."""

from pathlib import Path

import pytest

from coordinator.config import ConfigError, load_config
from coordinator.session import SessionKeyNotConfigured
from core.auth.api_key import AuthNotConfigured

# Constantes pour les valeurs par défaut
DEFAULT_PORT = 8080
DEFAULT_SERVER_URL = "http://localhost:3000"
TEST_PORT = 9000


def _base_env(**over: str) -> dict[str, str]:
    """Construit un environnement minimal valide."""
    env = {
        "COORDINATOR_API_KEY": "secret",
        "COORDINATOR_SESSION_KEY": "k" * 44,
        "COORDINATOR_POLICY_FILE": "/tmp/policy.yml",
    }
    env.update(over)
    return env


def test_loads_with_defaults() -> None:
    """Charge la config avec les valeurs par défaut."""
    cfg = load_config(_base_env())
    assert cfg.auth_secret == "secret"
    assert cfg.policy_file == Path("/tmp/policy.yml")
    assert cfg.audit_file == Path("audit.jsonl")
    assert cfg.session_dir == Path("sessions")
    assert cfg.host == "127.0.0.1" and cfg.port == DEFAULT_PORT
    assert cfg.agent_server_url == DEFAULT_SERVER_URL


def test_missing_auth_key_fails_closed() -> None:
    """Échoue immédiatement si COORDINATOR_API_KEY absent."""
    env = _base_env()
    del env["COORDINATOR_API_KEY"]
    with pytest.raises(AuthNotConfigured):
        load_config(env)


def test_missing_session_key_fails_closed() -> None:
    """Échoue immédiatement si COORDINATOR_SESSION_KEY absent."""
    env = _base_env()
    del env["COORDINATOR_SESSION_KEY"]
    with pytest.raises(SessionKeyNotConfigured):
        load_config(env)


def test_missing_policy_file_fails_closed() -> None:
    """Échoue immédiatement si COORDINATOR_POLICY_FILE absent."""
    env = _base_env()
    del env["COORDINATOR_POLICY_FILE"]
    with pytest.raises(ConfigError):
        load_config(env)


def test_overrides_applied() -> None:
    """Applique les surcharges depuis l'environnement."""
    cfg = load_config(
        _base_env(COORDINATOR_PORT=str(TEST_PORT), AGENT_SERVER_SOCK="/run/a.sock")
    )
    assert cfg.port == TEST_PORT
    assert cfg.agent_server_sock == "/run/a.sock"
