from core.tokens.vault import Vault, detokenize, tokenize


def _fake_extract(text: str) -> dict[str, list[str]]:
    # Extracteur déterministe de test — pas de spaCy.
    out: dict[str, list[str]] = {"IP": [], "VPN_USER": []}
    for tok in text.replace(",", " ").split():
        if tok.count(".") == 3 and tok.replace(".", "").isdigit():
            out["IP"].append(tok)
        elif tok.startswith("user:"):
            out["VPN_USER"].append(tok)
    return out


def test_tokenize_remplace_les_valeurs() -> None:
    v = Vault()
    out = tokenize("ban 10.0.0.5 et 10.0.0.6", v, _fake_extract)
    assert "10.0.0.5" not in out and "10.0.0.6" not in out
    assert "IP_1" in out and "IP_2" in out


def test_meme_valeur_meme_jeton_dans_la_session() -> None:
    v = Vault()
    out = tokenize("10.0.0.5 puis 10.0.0.5", v, _fake_extract)
    assert out.count("IP_1") == 2  # bijection stable dans la session


def test_round_trip() -> None:
    v = Vault()
    out = tokenize("ban 10.0.0.5", v, _fake_extract)
    assert detokenize(out, v) == "ban 10.0.0.5"


def test_detokenize_recursif_sur_struct() -> None:
    v = Vault()
    tokenize("10.0.0.5", v, _fake_extract)  # peuple le vault : IP_1 -> 10.0.0.5
    struct = {"cmd": "ban", "args": {"ip": "IP_1", "list": ["IP_1"]}}
    assert detokenize(struct, v) == {"cmd": "ban", "args": {"ip": "10.0.0.5", "list": ["10.0.0.5"]}}


def test_deux_sessions_sans_jeton_commun() -> None:
    v1, v2 = Vault(), Vault()
    tokenize("10.0.0.5", v1, _fake_extract)
    tokenize("10.0.0.9", v2, _fake_extract)
    # IP_1 de v1 et IP_1 de v2 designent des valeurs differentes -> pas de fuite inter-session
    assert v1.resolve("IP_1") == "10.0.0.5"
    assert v2.resolve("IP_1") == "10.0.0.9"


def test_property_aucune_valeur_du_vault_dans_le_texte_tokenise() -> None:
    v = Vault()
    out = tokenize("10.0.0.5 user:bob 10.0.0.6", v, _fake_extract)
    for real in v.values():
        assert real not in out
