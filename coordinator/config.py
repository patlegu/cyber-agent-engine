"""Chargement de la configuration du coordinateur — fail-closed sur les obligatoires.

Les secrets/chemins/endpoints viennent de l'environnement ; les règles de
politique d'un fichier YAML séparé (voir load_policy). Un obligatoire manquant
lève une erreur claire au démarrage plutôt qu'un crash opaque.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from coordinator.session import load_session_key
from core.auth.api_key import load_auth_secret


class ConfigError(Exception):
    """Configuration incomplète — le coordinateur ne doit pas démarrer."""


@dataclass(frozen=True)
class CoordinatorConfig:
    """Configuration du coordinateur — immutable après chargement."""

    auth_secret: str
    session_key: bytes
    policy_file: Path
    audit_file: Path
    session_dir: Path
    host: str
    port: int
    agent_server_url: str
    agent_server_sock: str
    agent_server_key: str


def load_config(env: Mapping[str, str]) -> CoordinatorConfig:
    """Charge la configuration du coordinateur depuis l'environnement.

    Lève AuthNotConfigured ou SessionKeyNotConfigured si les secrets obligatoires
    manquent (fail-closed). Lève ConfigError si COORDINATOR_POLICY_FILE manque.
    Les autres champs reçoivent des valeurs par défaut.

    Args:
        env: Mapping clé-valeur (typiquement os.environ)

    Returns:
        CoordinatorConfig configurée et validée

    Raises:
        AuthNotConfigured: COORDINATOR_API_KEY manquant
        SessionKeyNotConfigured: COORDINATOR_SESSION_KEY manquant
        ConfigError: COORDINATOR_POLICY_FILE manquant
    """
    auth_secret = load_auth_secret(env, "COORDINATOR_API_KEY")  # lève AuthNotConfigured
    session_key = load_session_key(env, "COORDINATOR_SESSION_KEY")  # lève SessionKeyNotConfigured

    policy_file = env.get("COORDINATOR_POLICY_FILE", "")
    if not policy_file:
        raise ConfigError("COORDINATOR_POLICY_FILE absent : chemin du policy.yml requis")

    return CoordinatorConfig(
        auth_secret=auth_secret,
        session_key=session_key,
        policy_file=Path(policy_file),
        audit_file=Path(env.get("COORDINATOR_AUDIT_FILE", "audit.jsonl")),
        session_dir=Path(env.get("COORDINATOR_SESSION_DIR", "sessions")),
        host=env.get("COORDINATOR_HOST", "127.0.0.1"),
        port=int(env.get("COORDINATOR_PORT", "8080")),
        agent_server_url=env.get("AGENT_SERVER_URL", "http://localhost:3000"),
        agent_server_sock=env.get("AGENT_SERVER_SOCK", ""),
        agent_server_key=env.get("AGENT_SERVER_KEY", ""),
    )
