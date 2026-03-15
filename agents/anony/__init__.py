"""
Package agents.anony — agent d'anonymisation de logs et documents de sécurité.

Utilise anonyfiles_core comme moteur (NER + remplacement + réversibilité).

Usage :
    from agents.anony import AnonyAgent

Structure :
    agent.py                      — AnonyAgent (orchestration, batch, session)
    config/
      custom_rules_security.json  — règles regex : IP RFC1918, CVE, FQDN, SVC…
"""

from .agent import AnonyAgent

__all__ = ["AnonyAgent"]
