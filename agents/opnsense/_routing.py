"""
Mixin pour la gestion du routage (Routing) OPNsense.
"""

from typing import Dict, Any
from ._decorators import safety_snapshot

class RoutingMixin:
    """
    Fonctionnalités OPNsense pour le Routage statique et les Passerelles (Gateways).
    """

    def _get_routing_tools(self) -> list[Dict[str, Any]]:
        """Définitions OAk des outils de Routage."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_static_routes",
                    "description": "Lister toutes les routes statiques configurées sur le firewall.",
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
                    "name": "add_static_route",
                    "description": "Ajouter une nouvelle route statique IPv4 ou IPv6 (ex: router 10.0.0.0/24 via la gateway WAN1).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "network": {
                                "type": "string",
                                "description": "Le réseau cible au format CIDR (ex: '10.0.1.0/24')."
                            },
                            "gateway": {
                                "type": "string",
                                "description": "Le nom système de la gateway à utiliser (ex: 'WAN_GW')."
                            },
                            "descr": {
                                "type": "string",
                                "description": "Une description optionnelle pour cette route.",
                                "default": ""
                            }
                        },
                        "required": ["network", "gateway"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "del_static_route",
                    "description": "Supprimer une route statique spécifique par son identifiant unique UUID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "uuid": {
                                "type": "string",
                                "description": "L'UUID de la route statique."
                            }
                        },
                        "required": ["uuid"]
                    }
                }
            }
        ]

    # ========================================================================
    # Implémentations
    # ========================================================================

    async def get_static_routes(self, _arguments: dict) -> str:
        res = await self.client.get_static_routes()
        return self._format_json(res)

    @safety_snapshot
    async def add_static_route(self, arguments: dict) -> str:
        res = await self.client.add_static_route(
            network=arguments['network'],
            gateway=arguments['gateway'],
            descr=arguments.get('descr', "")
        )
        return self._format_json(res)

    @safety_snapshot
    async def del_static_route(self, arguments: dict) -> str:
        res = await self.client.delete_static_route(arguments['uuid'])
        return self._format_json(res)
