from coordinator.extractor import build_regex_extractor

extract = build_regex_extractor()


def test_ipv4():
    assert extract("banni 203.0.113.9")["IP_ADDRESS"] == ["203.0.113.9"]


def test_cidr_not_split_as_ip():
    out = extract("réseau 198.51.100.0/24")
    assert out["IP_SUBNET"] == ["198.51.100.0/24"]
    assert out.get("IP_ADDRESS", []) == []  # le CIDR ne doit pas ré-émettre l'IP nue


def test_mac_and_cve_and_hash():
    text = "hôte 00:1b:44:11:3a:b7 vuln CVE-2021-44228 hash d41d8cd98f00b204e9800998ecf8427e"
    out = extract(text)
    assert out["MAC_ADDRESS"] == ["00:1b:44:11:3a:b7"]
    assert out["CVE"] == ["CVE-2021-44228"]
    assert out["HASH"] == ["d41d8cd98f00b204e9800998ecf8427e"]


def test_hostname_and_port():
    out = extract("connexion à srv-web-01.example.com:8443")
    assert "srv-web-01.example.com" in out["HOSTNAME"]
    assert "8443" in out["PORT_NUMBER"]


def test_dedupe_and_order():
    out = extract("1.2.3.4 puis 5.6.7.8 puis 1.2.3.4")
    assert out["IP_ADDRESS"] == ["1.2.3.4", "5.6.7.8"]


def test_no_false_positive_on_plain_words():
    out = extract("bonjour le monde")
    assert all(not v for v in out.values())


def test_ipv6_compressed():
    assert "2001:db8::42" in extract("bloque 2001:db8::42")["IP_ADDRESS"]


def test_ipv6_does_not_eat_mac():
    out = extract("hôte 00:1b:44:11:3a:b7 et 2001:db8::1")
    assert out["MAC_ADDRESS"] == ["00:1b:44:11:3a:b7"]
    assert "2001:db8::1" in out["IP_ADDRESS"]


def test_uppercase_hash():
    out = extract("hash D41D8CD98F00B204E9800998ECF8427E")
    assert "D41D8CD98F00B204E9800998ECF8427E" in out["HASH"]
