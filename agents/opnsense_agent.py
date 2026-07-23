# SPDX-License-Identifier: AGPL-3.0-or-later
"""
agents/opnsense_agent.py — Compatibilité ascendante.

L'implémentation complète a été déplacée dans le package agents/opnsense/.
Ce fichier conserve l'import public pour ne pas casser les imports existants.
"""

from agents.opnsense import OPNsenseAgent, safety_snapshot  # noqa: F401

__all__ = ["OPNsenseAgent", "safety_snapshot"]
