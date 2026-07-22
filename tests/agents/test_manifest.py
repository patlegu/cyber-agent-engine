"""Tests du manifeste de capacités CrowdSec et de sa conformance avec l'agent live."""

import pytest

from agents.crowdsec_agent import CrowdSecAgent
from agents.manifest import ManifestConformanceError, check_conformance, load_manifest


def test_load_manifest_namespaces():
    caps = load_manifest("crowdsec")
    names = {c.name for c in caps}
    assert "crowdsec.ban_ip" in names
    ban = next(c for c in caps if c.name == "crowdsec.ban_ip")
    assert ban.required_args == ["ip"]
    assert len(caps) == 15  # noqa: PLR2004


def test_conformance_matches_live_agent():
    agent = CrowdSecAgent(model_path=None)
    check_conformance("crowdsec", agent.get_capabilities())  # ne lève pas


def test_conformance_detects_drift():
    live = [{"name": "ban_ip", "parameters": {"required": ["ip", "DRIFT"]}}]
    with pytest.raises(ManifestConformanceError):
        check_conformance("crowdsec", live)
