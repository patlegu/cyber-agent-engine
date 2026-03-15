"""
Package agents.opnsense — re-exporte OPNsenseAgent pour la compatibilité ascendante.

Usage (inchangé) :
    from agents.opnsense_agent import OPNsenseAgent
    from agents.opnsense import OPNsenseAgent
"""

from ._base import OPNsenseAgent
from ._decorators import safety_snapshot

__all__ = ["OPNsenseAgent", "safety_snapshot"]
