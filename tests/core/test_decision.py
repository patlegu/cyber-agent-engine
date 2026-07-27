from core.audit.sink import MemoryAuditSink
from core.decision import decide
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import ArgMatch, Intention, Match, Rule


def _catalog():
    return CapabilityCatalog([Capability(name="crowdsec.ban_ip", required_args=["ip"])])


def _catalog_opnsense():
    return CapabilityCatalog([Capability(name="opnsense.block_ip", required_args=["ip"])])


def test_decide_allows_and_audits():
    sink = MemoryAuditSink()
    policy = [Rule(match=Match(capability="crowdsec.ban_ip"), effect="allow")]
    v = decide(Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"}),
               catalog=_catalog(), policy=policy, sink=sink)
    assert v.effect == "allow"
    assert sink.entries[-1].capability == "crowdsec.ban_ip"


def test_decide_default_deny():
    sink = MemoryAuditSink()
    v = decide(Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"}),
               catalog=_catalog(), policy=[], sink=sink)
    assert v.effect == "deny"


def test_deny_on_private_scope():
    """Une règle peut matcher sur le pseudo-arg ``ip__scope`` sans que la
    politique elle-même connaisse la notion de scope (moteur inchangé)."""
    sink = MemoryAuditSink()
    rule = Rule(
        match=Match(
            capability="opnsense.block_*",
            args={"ip__scope": ArgMatch(op="eq", value="private")},
        ),
        effect="deny",
        reason="ip privée",
    )
    intention = Intention(capability="opnsense.block_ip", args={"ip": "IP_ADDRESS_1"})
    v = decide(
        intention,
        catalog=_catalog_opnsense(),
        policy=[rule],
        sink=sink,
        arg_meta={"ip": {"scope": "private"}},
    )
    assert v.effect == "deny"
    # Aucune clé synthétique ne fuit dans l'intention du verdict.
    assert "ip__scope" not in v.intention.args
    assert v.intention.args == {"ip": "IP_ADDRESS_1"}
    # Ni dans l'entrée d'audit.
    assert "ip__scope" not in sink.entries[-1].args
    assert sink.entries[-1].args == {"ip": "IP_ADDRESS_1"}


def test_public_scope_not_denied_by_private_rule():
    sink = MemoryAuditSink()
    rule = Rule(
        match=Match(
            capability="opnsense.block_*",
            args={"ip__scope": ArgMatch(op="eq", value="private")},
        ),
        effect="deny",
    )
    allow = Rule(match=Match(capability="opnsense.block_*"), effect="approve")
    intention = Intention(capability="opnsense.block_ip", args={"ip": "IP_ADDRESS_1"})
    v = decide(
        intention,
        catalog=_catalog_opnsense(),
        policy=[rule, allow],
        sink=sink,
        arg_meta={"ip": {"scope": "public"}},
    )
    assert v.effect == "approve"
    assert "ip__scope" not in v.intention.args


def test_backward_compatible_without_arg_meta():
    sink = MemoryAuditSink()
    allow = Rule(match=Match(capability="opnsense.block_*"), effect="approve")
    intention = Intention(capability="opnsense.block_ip", args={"ip": "IP_ADDRESS_1"})
    v = decide(intention, catalog=_catalog_opnsense(), policy=[allow], sink=sink)
    assert v.effect == "approve"
    assert v.intention.args == {"ip": "IP_ADDRESS_1"}
