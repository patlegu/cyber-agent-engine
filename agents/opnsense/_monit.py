"""
Mixin pour la gestion de Monit (Surveillance des services et auto-réparation) OPNsense.
"""

from typing import Dict, Any, Literal
from ._decorators import safety_snapshot

class MonitMixin:
    """
    Fonctionnalités OPNsense pour Monit (Service Monitoring & Self-Healing).
    """

    def _get_monit_tools(self) -> list[Dict[str, Any]]:
        """Définitions OAk des outils Monit."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_monit_status",
                    "description": "Récupérer l'état actuel de tous les services surveillés par Monit (statut, pannes, uptime).",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "restart_monit_service",
                    "description": "Actionner un service géré par Monit (par exemple: forcer le redémarrage d'un service planté comme Unbound ou Suricata).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "description": "L'action à effectuer : 'start', 'stop', 'restart', 'monitor', 'unmonitor'.",
                                "enum": ["start", "stop", "restart", "monitor", "unmonitor"]
                            },
                            "service": {
                                "type": "string",
                                "description": "L'UUID ou le nom du service Monit cible."
                            }
                        },
                        "required": ["action", "service"]
                    }
                }
            }
        ]

    # ========================================================================
    # Implémentations
    # ========================================================================

    async def get_monit_status(self, _arguments: dict) -> str:
        res = await self.client.get_monit_status()
        return self._format_json(res)

    @safety_snapshot
    async def restart_monit_service(self, arguments: dict) -> str:
        action = arguments['action']
        service = arguments['service']
        
        res = await self.client.restart_monit_service(action, service)
        return self._format_json(res)
