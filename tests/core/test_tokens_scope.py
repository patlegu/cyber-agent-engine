# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests pour ``classify_ip`` et le meta ``scope`` porté par les jetons IP du Vault.

Objectif : le LLM/la policy doivent pouvoir raisonner sur la nature d'une IP
(publique, privée, loopback, link-local, réservée) SANS jamais voir l'adresse
elle-même. Le meta est dérivé (classe), jamais la valeur brute.
"""

from core.tokens.vault import Vault, classify_ip


def test_classify_ip_classes() -> None:
    assert classify_ip("8.8.8.8") == "public"
    assert classify_ip("10.1.2.3") == "private"
    assert classify_ip("192.168.1.1") == "private"
    assert classify_ip("172.16.0.1") == "private"
    assert classify_ip("127.0.0.1") == "loopback"
    assert classify_ip("169.254.1.1") == "link_local"
    assert classify_ip("fd00::1") == "private"  # ULA
    assert classify_ip("2620:fe::9") == "public"
    assert classify_ip("10.0.0.0/8") == "private"  # subnet CIDR
    assert classify_ip("pas-une-ip") is None
    assert classify_ip("") is None


def test_classify_ip_documentation_range_is_non_none() -> None:
    # Plage de documentation RFC5737 (203.0.113.0/24, TEST-NET-3) utilisée par la démo.
    # is_private/is_global pour ces plages varient selon la version de Python (CPython a
    # marqué is_private=True plus récemment pour ces réseaux). On n'affirme donc PAS une
    # classe devinée : on vérifie juste que classify_ip retourne une classe non vide, et on
    # documente la valeur observée localement.
    # Observé : Python 3.11.2 -> is_private=True, is_global=False -> classify_ip == "private".
    result = classify_ip("203.0.113.45")
    assert result is not None
    assert isinstance(result, str)


def test_vault_stores_scope_for_ip_only() -> None:
    v = Vault()
    tok_ip = v.token_for("IP_ADDRESS", "10.0.0.5")
    tok_sub = v.token_for("IP_SUBNET", "192.168.0.0/24")
    tok_host = v.token_for("HOSTNAME", "example.com")
    assert v.meta(tok_ip) == {"scope": "private"}
    assert v.meta(tok_sub) == {"scope": "private"}
    assert v.meta(tok_host) == {}  # pas de scope pour un hostname
    assert v.meta("INEXISTANT_1") == {}


def test_vault_reused_token_keeps_its_meta() -> None:
    v = Vault()
    tok1 = v.token_for("IP_ADDRESS", "8.8.8.8")
    tok2 = v.token_for("IP_ADDRESS", "8.8.8.8")  # même valeur -> même jeton réutilisé
    assert tok1 == tok2
    assert v.meta(tok1) == {"scope": "public"}


def test_meta_survives_snapshot_restore() -> None:
    v = Vault()
    tok = v.token_for("IP_ADDRESS", "8.8.8.8")
    v2 = Vault.restore(v.snapshot())
    assert v2.meta(tok) == {"scope": "public"}
    assert v2.resolve(tok) == "8.8.8.8"


def test_restore_reste_compatible_avec_un_snapshot_sans_meta() -> None:
    # Rétrocompatibilité : un ancien snapshot sans clé "meta" doit se restaurer sans erreur.
    v = Vault()
    tok = v.token_for("IP_ADDRESS", "10.0.0.5")
    snap = v.snapshot()
    del snap["meta"]
    v2 = Vault.restore(snap)
    assert v2.resolve(tok) == "10.0.0.5"
    assert v2.meta(tok) == {}


def test_meta_never_contains_value() -> None:
    v = Vault()
    v.token_for("IP_ADDRESS", "203.0.113.45")
    dumped = str(v.meta_items())
    assert "203.0.113.45" not in dumped  # zéro-secret : la classe, pas la valeur
