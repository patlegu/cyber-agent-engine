# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Gestion des alias — 10 méthodes.
"""

import logging
from typing import Dict, List, Optional

from ._decorators import safety_snapshot

logger = logging.getLogger(__name__)


class AliasesMixin:

    @safety_snapshot
    async def _create_alias(self, name: str, type: str, content: List[str], description: str = "") -> Dict:
        """Crée un alias (host, network, port, url, geoip)."""
        logger.info(f"[OPNsense] Création alias: {name} (type: {type})")

        if self._api_client:
            try:
                alias_data = {
                    "alias": {
                        "name": name,
                        "type": type,
                        "content": "\n".join(content),
                        "description": description,
                        "enabled": "1"
                    }
                }
                response = await self._api_client.add_alias(alias_data)
                if response.get('result') == 'saved':
                    await self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Alias '{name}' créé et appliqué")
                return response
            except Exception as e:
                logger.error(f"Erreur création alias: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "created", "uuid": f"alias-{hash(name) % 10000}", "name": name, "mode": "simulation"}

    @safety_snapshot
    async def _delete_alias(self, uuid: str) -> Dict:
        """Supprime un alias."""
        logger.info(f"[OPNsense] Suppression alias: {uuid}")

        if self._api_client:
            try:
                response = await self._api_client.delete_alias(uuid)
                if response.get('result') == 'deleted':
                    await self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Alias {uuid} supprimé")
                return response
            except Exception as e:
                logger.error(f"Erreur suppression alias: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "deleted", "uuid": uuid, "mode": "simulation"}

    @safety_snapshot
    async def _update_alias(self, uuid: str, **kwargs) -> Dict:
        """Modifie un alias existant."""
        logger.info(f"[OPNsense] Modification alias: {uuid}")

        if self._api_client:
            try:
                if 'content' in kwargs and isinstance(kwargs['content'], list):
                    kwargs['content'] = "\n".join(kwargs['content'])
                alias_data = {"alias": {k: v for k, v in kwargs.items() if v is not None}}
                response = await self._api_client.update_alias(uuid, alias_data)
                if response.get('result') == 'saved':
                    await self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Alias {uuid} modifié")
                return response
            except Exception as e:
                logger.error(f"Erreur modification alias: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "updated", "uuid": uuid, "mode": "simulation"}

    async def _get_alias(self, uuid: Optional[str] = None) -> Dict:
        """Récupère un ou tous les alias."""
        logger.info(f"[OPNsense] Consultation alias{f': {uuid}' if uuid else ''}")

        if self._api_client:
            try:
                return await self._api_client.get_alias(uuid)
            except Exception as e:
                logger.error(f"Erreur consultation alias: {e}")
                return {"status": "error", "message": str(e)}

        return {"total": 15, "aliases": [], "mode": "simulation"}

    @safety_snapshot
    async def _import_alias(self, uuid: str, content: str) -> Dict:
        """Importe des entrées dans un alias depuis un fichier/URL."""
        logger.info(f"[OPNsense] Import dans alias: {uuid}")

        if self._api_client:
            try:
                response = await self._api_client.import_alias(uuid, content)
                if response.get('result') == 'saved':
                    await self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Import dans alias {uuid} effectué")
                return response
            except Exception as e:
                logger.error(f"Erreur import alias: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "imported", "uuid": uuid, "mode": "simulation"}

    @safety_snapshot
    async def _flush_alias(self, alias: str) -> Dict:
        """Vide toutes les entrées d'un alias."""
        logger.info(f"[OPNsense] Flush alias: {alias}")

        if self._api_client:
            try:
                response = await self._api_client.flush_alias(alias)
                # Success checks for 'flushed' (older) or 'success' (standard)
                if response.get('result') == 'flushed' or response.get('status') == 'success':
                    logger.info(f"✓ Alias {alias} vidé")
                return response
            except Exception as e:
                logger.error(f"Erreur flush alias: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "flushed", "alias": alias, "mode": "simulation"}

    @safety_snapshot
    async def _add_to_alias(self, alias: str, address: str) -> Dict:
        """Ajoute une entrée à un alias."""
        logger.info(f"[OPNsense] Ajout {address} à alias {alias}")

        if self._api_client:
            try:
                response = await self._api_client.add_to_alias(alias, address)
                if response.get('result') == 'added' or response.get('status') == 'success':
                    logger.info(f"✓ {address} ajouté à {alias}")
                return response
            except Exception as e:
                logger.error(f"Erreur ajout à alias: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "added", "alias": alias, "address": address, "mode": "simulation"}

    @safety_snapshot
    async def _delete_from_alias(self, alias: str, address: str) -> Dict:
        """Retire une entrée d'un alias."""
        logger.info(f"[OPNsense] Retrait {address} de alias {alias}")

        if self._api_client:
            try:
                response = await self._api_client.delete_from_alias(alias, address)
                if response.get('result') == 'removed' or response.get('status') == 'success':
                    logger.info(f"✓ {address} retiré de {alias}")
                return response
            except Exception as e:
                logger.error(f"Erreur retrait alias: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "removed", "alias": alias, "address": address, "mode": "simulation"}

    async def _list_alias_content(self, alias: str) -> Dict:
        """Liste le contenu actuel d'un alias (table PF)."""
        logger.info(f"[OPNsense] Liste contenu alias: {alias}")

        if self._api_client:
            try:
                return await self._api_client.list_alias_content(alias)
            except Exception as e:
                logger.error(f"Erreur liste contenu alias: {e}")
                return {"status": "error", "message": str(e)}

        return {"alias": alias, "content": [], "mode": "simulation"}

    async def _find_alias_references(self, alias: str) -> Dict:
        """Trouve où un alias est utilisé."""
        logger.info(f"[OPNsense] Recherche références alias: {alias}")

        if self._api_client:
            try:
                return await self._api_client.find_alias_references(alias)
            except Exception as e:
                logger.error(f"Erreur recherche références: {e}")
                return {"status": "error", "message": str(e)}

        return {"alias": alias, "references": [], "mode": "simulation"}
