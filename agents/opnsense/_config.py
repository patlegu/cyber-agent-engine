# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Gestion de configuration + Backup/Restore — 9 méthodes.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ConfigMixin:

    async def _apply_firewall_changes(self, rollback_timeout: int = 0) -> Dict:
        """Applique les modifications du firewall."""
        logger.info(f"[OPNsense] Application changements{f' (rollback: {rollback_timeout}s)' if rollback_timeout else ''}")

        if self._api_client:
            try:
                response = await self._api_client.apply_firewall_changes(rollback_timeout)
                if response.get('status') == 'ok':
                    logger.info("✓ Changes applied successfully")
                return response
            except Exception as e:
                logger.error(f"Erreur application changements: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "applied", "rollback_timeout": rollback_timeout, "mode": "simulation"}

    async def _cancel_firewall_rollback(self) -> Dict:
        """Annule le rollback automatique (confirme les changements)."""
        logger.info("[OPNsense] Annulation rollback")

        if self._api_client:
            try:
                response = await self._api_client.cancel_firewall_rollback()
                logger.info("✓ Rollback cancelled, changes confirmed")
                return response
            except Exception as e:
                logger.error(f"Erreur annulation rollback: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "confirmed", "mode": "simulation"}

    async def _revert_firewall_changes(self) -> Dict:
        """Annule les changements non appliqués."""
        logger.info("[OPNsense] Revert changements")

        if self._api_client:
            try:
                response = await self._api_client.revert_firewall_changes()
                logger.info("✓ Changes cancelled")
                return response
            except Exception as e:
                logger.error(f"Erreur revert: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "reverted", "mode": "simulation"}

    async def _create_firewall_savepoint(self, revision: Optional[str] = None) -> Dict:
        """Crée un point de sauvegarde."""
        logger.info(f"[OPNsense] Creating savepoint{f': {revision}' if revision else ''}")

        if self._api_client:
            try:
                response = await self._api_client.create_firewall_savepoint(revision)
                logger.info(f"✓ Savepoint created: {response.get('revision', 'auto')}")
                return response
            except Exception as e:
                logger.error(f"Savepoint creation error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "saved", "revision": revision or "auto", "mode": "simulation"}

    async def _get_interface_list(self) -> Dict:
        """Liste toutes les interfaces réseau (via l'overview officiel)."""
        logger.info("[OPNsense] Liste interfaces")

        if self._api_client:
            try:
                return await self._api_client.get_interface_list()
            except Exception as e:
                logger.error(f"Erreur liste interfaces: {e}")
                return {"status": "error", "message": str(e)}

        return {"interfaces": ["wan", "lan", "opt1", "opt2"], "mode": "simulation"}

    # --- Backup / Restore ---

    async def _backup_configuration(self) -> Dict:
        """Télécharge la configuration complète (XML)."""
        logger.info("[OPNsense] Downloading configuration backup")

        if self._api_client:
            try:
                import os
                from datetime import datetime

                xml_content = await self._api_client.download_configuration()
                size_kb = len(xml_content) / 1024

                backup_dir = "backups"
                os.makedirs(backup_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{backup_dir}/config-{timestamp}.xml"

                with open(filename, "w") as f:
                    f.write(xml_content)

                return {
                    "status": "success",
                    "message": "Configuration downloaded and saved locally",
                    "file": filename,
                    "size_kb": f"{size_kb:.2f} KB"
                }
            except Exception as e:
                logger.error(f"Erreur backup configuration: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "success", "mode": "simulation", "message": "Fake backup downloaded"}

    async def _list_restore_points(self) -> Dict:
        """Liste les points de restauration disponibles."""
        logger.info("[OPNsense] Liste points de restauration")

        if self._api_client:
            try:
                return await self._api_client.list_restore_points()
            except Exception as e:
                logger.error(f"Erreur liste restore points: {e}")
                return {"status": "error", "message": str(e)}

        return {
            "backups": [
                {"timestamp": "1678886400", "description": "Auto-saved by system"},
                {"timestamp": "1678882800", "description": "Manual backup"}
            ],
            "mode": "simulation"
        }

    async def _revert_to_restore_point(self, revision_id: str) -> Dict:
        """Restaure une configuration précédente."""
        logger.info(f"[OPNsense] Restauration point: {revision_id}")

        if self._api_client:
            try:
                response = await self._api_client.revert_to_restore_point(revision_id)
                logger.warning(f"⚠ Restore triggered ({revision_id}). The system may reboot.")
                return response
            except Exception as e:
                logger.error(f"Erreur restauration: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "restored", "revision": revision_id, "mode": "simulation"}

    async def _create_restore_point(self, description: str = "Agent Checkpoint") -> Dict:
        """Crée un point de sauvegarde de sécurité avant des changements risqués."""
        logger.info(f"[OPNsense] Creating backup point: {description}")

        if self._api_client:
            try:
                return await self._api_client.create_firewall_savepoint(revision=description)
            except Exception as e:
                logger.error(f"Savepoint creation error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "saved", "revision": description, "mode": "simulation"}
