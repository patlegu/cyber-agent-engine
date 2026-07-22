from core.audit.sink import MemoryAuditSink
from core.decision import decide
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import Intention, Match, Rule


def _catalog():
    return CapabilityCatalog([Capability(name="crowdsec.ban_ip", required_args=["ip"])])


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
