# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Mixin pour la gestion du système de détection d'intrusion (IDS / Suricata) OPNsense.
"""

from typing import Dict, Any

class IDSMixin:
    """
    Fonctionnalités OPNsense pour Suricata (Intrusion Detection System).
    """

    def _get_ids_tools(self) -> list[Dict[str, Any]]:
        """Définitions OAk des outils IDS."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_ids_status",
                    "description": "Récupérer l'état actuel du service IDS (Suricata) sur OPNsense.",
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
                    "name": "query_ids_alerts",
                    "description": "Interroger les journaux d'alertes IDS (Suricata). Utile pour voir quelles adresses IP déclenchent des règles.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "description": "Nombre maximum de résultats (défaut 100).",
                                "default": 100
                            },
                            "search_phrase": {
                                "type": "string",
                                "description": "Terme de recherche optionnel (ex: une IP ou le nom d'une attaque)."
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "toggle_ids_rule",
                    "description": "Activer ou désactiver une règle IDS spécifique via son SID (Signature ID) et recharger le service.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sid": {
                                "type": "string",
                                "description": "Le SID (Signature ID) de la règle Suricata (ex: '2012865')."
                            },
                            "enabled": {
                                "type": "integer",
                                "description": "1 pour activer la règle, 0 pour la désactiver."
                            }
                        },
                        "required": ["sid", "enabled"]
                    }
                }
            }
        ]

    # ========================================================================
    # Implémentations
    # ========================================================================

    async def get_ids_status(self, _arguments: dict) -> str:
        res = await self.client.get_ids_status()
        return self._format_json(res)

    async def query_ids_alerts(self, arguments: dict) -> str:
        limit = arguments.get('limit', 100)
        search_phrase = arguments.get('search_phrase', "")
        
        res = await self.client.query_ids_alerts(
            limit=limit,
            search_phrase=search_phrase
        )
        return self._format_json(res)

    async def toggle_ids_rule(self, arguments: dict) -> str:
        sid = arguments['sid']
        enabled = arguments['enabled']
        
        # 1. Toggle la règle
        toggle_res = await self.client.toggle_ids_rule(sid, enabled)
        
        # 2. Recharger le service IDS pour appliquer
        reload_res = await self.client.reload_ids_rules()
        
        return self._format_json({
            "toggle_result": toggle_res,
            "reload_result": reload_res
        })

    # ========================================================================
    # Lot 1 — IDS complémentaire
    # ========================================================================

    async def _list_ids_rulesets(self) -> Dict:
        """Liste les rulesets IDS Suricata disponibles avec leur état d'activation.

        Retourne les rulesets installés (Emerging Threats, etc.) et leur statut.
        """
        logger.info("[OPNsense] Liste des rulesets IDS")
        if self._api_client:
            try:
                return await self._api_client.list_ids_rulesets()
            except Exception as e:
                logger.error(f"Erreur liste rulesets IDS: {e}")
                return {"status": "error", "message": str(e)}
        return {"rulesets": [], "mode": "simulation"}

    async def _toggle_ids_ruleset(self, filename: str, enabled: int) -> Dict:
        """Active ou désactive un ruleset IDS Suricata par son nom de fichier.

        :param filename: Nom du fichier ruleset (ex: 'emerging-threats.rules').
        :param enabled: 1 pour activer, 0 pour désactiver.
        """
        logger.info(f"[OPNsense] Toggle ruleset IDS: {filename} → {'on' if enabled else 'off'}")
        if self._api_client:
            try:
                response = await self._api_client.toggle_ids_ruleset(filename, enabled)
                await self._api_client.reload_ids_rules()
                return response
            except Exception as e:
                logger.error(f"Erreur toggle ruleset IDS: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "toggled", "filename": filename, "enabled": enabled, "mode": "simulation"}

    async def _update_ids_rules(self) -> Dict:
        """Met à jour les règles IDS depuis les sources upstream (ET, Snort, etc.).

        Télécharge et installe la dernière version des signatures de détection.
        """
        logger.info("[OPNsense] Updating IDS rules")
        if self._api_client:
            try:
                return await self._api_client.update_ids_rules()
            except Exception as e:
                logger.error(f"IDS rules update error: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "updated", "mode": "simulation"}

    async def _start_ids(self) -> Dict:
        """Démarre le service IDS Suricata sur OPNsense."""
        logger.info("[OPNsense] Starting IDS")
        if self._api_client:
            try:
                return await self._api_client.start_ids()
            except Exception as e:
                logger.error(f"IDS startup error: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "started", "mode": "simulation"}

    async def _stop_ids(self) -> Dict:
        """Arrête le service IDS Suricata sur OPNsense."""
        logger.info("[OPNsense] Stopping IDS")
        if self._api_client:
            try:
                return await self._api_client.stop_ids()
            except Exception as e:
                logger.error(f"IDS stop error: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "stopped", "mode": "simulation"}

    async def _restart_ids(self) -> Dict:
        """Redémarre le service IDS Suricata (applique les changements de config)."""
        logger.info("[OPNsense] Restarting IDS")
        if self._api_client:
            try:
                return await self._api_client.restart_ids()
            except Exception as e:
                logger.error(f"IDS restart error: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "restarted", "mode": "simulation"}
