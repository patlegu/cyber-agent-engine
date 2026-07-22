from pathlib import Path

from cryptography.fernet import Fernet

from coordinator.app import build_agent_clients
from coordinator.config import CoordinatorConfig


def _cfg(*, agent_servers, sock="") -> CoordinatorConfig:
    return CoordinatorConfig(
        auth_secret="s", session_key=Fernet.generate_key(), policy_file=Path("/tmp/p.yml"),
        audit_file=Path("/tmp/a.jsonl"), session_dir=Path("/tmp/s"), host="127.0.0.1", port=8080,
        agent_server_url=agent_servers[0], agent_server_sock=sock, agent_server_key="k",
        agent_servers=agent_servers, audit_max_bytes=0, audit_backups=0,
    )


def test_single_server_uses_socket():
    clients = build_agent_clients(_cfg(agent_servers=["http://x:3000"], sock="/run/a.sock"))
    assert len(clients) == 1
    assert clients[0]._socket_path == "/run/a.sock"


def test_multiple_servers_no_socket():
    clients = build_agent_clients(_cfg(agent_servers=["http://a:3000", "http://b:3000"]))
    assert len(clients) == 2  # noqa: PLR2004
    assert [c._base_url for c in clients] == ["http://a:3000", "http://b:3000"]
    assert all(c._socket_path == "" for c in clients)
