from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from coordinator.session import (
    EncryptedFileSessionStore,
    MemorySessionStore,
    SessionKeyNotConfigured,
    SessionState,
    load_session_key,
)


def _state(exp: float = 100.0) -> SessionState:
    return SessionState(
        id="s1",
        request_tokens="banni IP_1",
        vault_snapshot={},
        history=[],
        step=0,
        expires_at=exp,
    )


def test_memory_expiry_purges() -> None:
    store = MemorySessionStore()
    store.save(_state(exp=100.0))
    assert store.get("s1", now=50.0) is not None
    assert store.get("s1", now=150.0) is None
    assert store.get("s1", now=50.0) is None  # purgé


def test_encrypted_file_roundtrip(tmp_path: Path) -> None:
    store = EncryptedFileSessionStore(tmp_path, Fernet.generate_key())
    store.save(_state())
    got = store.get("s1", now=50.0)
    assert got is not None and got.request_tokens == "banni IP_1"
    # le fichier sur disque ne contient pas le clair
    blob = (tmp_path / "s1.session").read_bytes()
    assert b"banni" not in blob


def test_load_key_fail_closed() -> None:
    with pytest.raises(SessionKeyNotConfigured):
        load_session_key({}, "COORDINATOR_SESSION_KEY")
