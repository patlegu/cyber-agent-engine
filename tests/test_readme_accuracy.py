"""Locks the doc-code coherence fixes from the 2026-07-23 README audit.

Each assertion targets a specific stale/false claim that was found drifted
from the code (see .superpowers/sdd/readme-audit.md) — regressions here mean
one of those claims crept back in.
"""

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_readmes_do_not_claim_configurable_checkpoint_timeout():
    # CHECKPOINT_TIMEOUT never existed; session_ttl is a hardcoded 300s
    # (coordinator/loop.py), not read from the environment.
    for name in ("README.md", "README.fr.md"):
        text = (_ROOT / name).read_text(encoding="utf-8")
        assert "CHECKPOINT_TIMEOUT" not in text


def test_readmes_do_not_reference_pilot_py():
    # coordinator/pilot.py, judge.py, state.py were removed long ago;
    # the coordinator is app.py/loop.py/proposer.py/... (core/ trust core).
    for name in ("README.md", "README.fr.md"):
        text = (_ROOT / name).read_text(encoding="utf-8")
        assert "pilot.py" not in text


def test_readmes_do_not_claim_infer_wiring_is_inactive():
    # agents/infer_wiring.py is wired into server.py — AGENT_INFER_BASE_URL /
    # AGENT_INFER_API_KEY / AGENT_LORA_MODELS ARE read by the code.
    en = (_ROOT / "README.md").read_text(encoding="utf-8")
    fr = (_ROOT / "README.fr.md").read_text(encoding="utf-8")
    assert "not read by the code" not in en
    assert "ne sont pas lus" not in fr


def test_readmes_document_the_trust_core_in_structure():
    for name in ("README.md", "README.fr.md"):
        text = (_ROOT / name).read_text(encoding="utf-8")
        assert "core/" in text


def test_readmes_do_not_instruct_running_dashboard_as_a_script():
    # `python dashboard/app.py` starts nothing; the dashboard is an ASGI app
    # started via uvicorn (dashboard.app:app).
    for name in ("README.md", "README.fr.md"):
        text = (_ROOT / name).read_text(encoding="utf-8")
        assert "python dashboard/app.py" not in text


def test_readmes_annotate_registered_agents():
    # server.py registers only 3 agents: opnsense, wireguard, crowdsec.
    # pfSense is available in code but not registered; AnonyAgent runs
    # in-process on the coordinator side. The READMEs must annotate this.
    en = (_ROOT / "README.md").read_text(encoding="utf-8")
    fr = (_ROOT / "README.fr.md").read_text(encoding="utf-8")
    assert "registered: opnsense, wireguard, crowdsec" in en
    assert "enregistrés : opnsense, wireguard, crowdsec" in fr
