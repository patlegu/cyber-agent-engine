import pytest

from agents.crowdsec_agent import CrowdSecAgent
from agents.manifest import ManifestConformanceError
from coordinator.catalog_builder import build_catalog


@pytest.mark.asyncio
async def test_build_catalog_from_live_agent():
    live = {"crowdsec": CrowdSecAgent(model_path=None).get_capabilities()}
    catalog = await build_catalog(["crowdsec"], live)
    assert "crowdsec.ban_ip" in catalog.names()
    assert len(catalog.names()) == 15  # noqa: PLR2004


@pytest.mark.asyncio
async def test_unreachable_agent_still_in_catalog():
    catalog = await build_catalog(["crowdsec"], {})  # aucun live -> pas de conformance
    assert "crowdsec.ban_ip" in catalog.names()


@pytest.mark.asyncio
async def test_drift_refuses():
    live = {"crowdsec": [{"name": "ban_ip", "required": ["ip", "DRIFT"]}]}
    with pytest.raises(ManifestConformanceError):
        await build_catalog(["crowdsec"], live)
