from core.audit.sink import AuditEntry, MemoryAuditSink, entry_from_verdict
from core.policy.models import Intention, Verdict
from core.tokens.vault import Vault, tokenize


def _extract(text: str) -> dict[str, list[str]]:
    return {"IP": [t for t in text.split() if t.count(".") == 3]}


def test_entry_from_verdict_ne_porte_que_des_jetons() -> None:
    v = Vault()
    tok = tokenize("10.0.0.5", v, _extract)
    it = Intention(capability="crowdsec.add_ban", args={"ip": tok})
    verdict = Verdict(effect="deny", matched_rule=None, intention=it)
    entry = entry_from_verdict(verdict, event="policy_decision")
    assert entry.effect == "deny"
    assert entry.args == {"ip": "IP_1"}


def test_property_aucune_valeur_reelle_dans_l_audit() -> None:
    v = Vault()
    tok = tokenize("10.0.0.5", v, _extract)
    it = Intention(capability="crowdsec.add_ban", args={"ip": tok})
    sink = MemoryAuditSink()
    sink.write(entry_from_verdict(Verdict(effect="allow", matched_rule=None, intention=it), event="e"))
    serialized = "".join(e.model_dump_json() for e in sink.entries)
    for real in v.values():
        assert real not in serialized  # le vault ne fuite jamais dans l'audit
