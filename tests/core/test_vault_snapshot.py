from core.tokens.vault import Vault


def test_vault_snapshot_roundtrip() -> None:
    v = Vault()
    t = v.token_for("IP", "203.0.113.9")
    restored = Vault.restore(v.snapshot())
    assert restored.resolve(t) == "203.0.113.9"
    # la numérotation continue sans collision
    assert restored.token_for("IP", "198.51.100.4") != t
