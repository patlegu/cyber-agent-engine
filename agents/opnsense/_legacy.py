# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Fonctions legacy — block_ip / unblock_ip.
"""

import logging
from typing import Dict, Optional

from ._decorators import safety_snapshot

logger = logging.getLogger(__name__)


class LegacyMixin:

    async def _block_ip(self, ip: Optional[str] = None, description: str = "Blocked by agent", **kwargs) -> Dict:
        """Bloque une adresse IP (legacy - utilise add_to_alias en interne)."""
        target_ip = ip or kwargs.get("address")
        if not target_ip:
            return {"status": "error", "message": "Missing 'ip' or 'address' parameter"}

        logger.info(f"[OPNsense] Blocage IP: {target_ip}")

        if self._api_client:
            if self.platform == "linux":
                return await self._api_client.crowdsec_block(target_ip, description)

            try:
                result = await self._add_to_alias("BlockedIPs", target_ip)

                status = result.get("status") or ""
                msg = str(result.get("message", "")).lower()

                if status == "error" and ("not found" in msg or "doesn't exist" in msg):
                    logger.info("BlockedIPs alias not found, creating...")
                    create_res = await self._create_alias(
                        name="BlockedIPs",
                        type="host",
                        content=[target_ip],
                        description="Auto-created by AI Agent"
                    )
                    if create_res.get("status") == "error":
                        return create_res
                    return {"status": "success", "ip": target_ip, "message": "Alias created and IP added"}

                if result.get("result") != "added":
                    uuid = await self._api_client.get_alias_uuid("BlockedIPs")
                    if uuid:
                        details = await self._api_client.get_alias(uuid)
                        content = str(details.get("alias", {}).get("content", ""))
                        if target_ip in content:
                            return {"status": "success", "ip": target_ip, "message": "Already blocked"}

                return result
            except Exception as e:
                logger.error(f"Erreur fatale blocage IP: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "success", "ip": target_ip, "mode": "simulation"}

    async def _unblock_ip(self, ip: Optional[str] = None, **kwargs) -> Dict:
        """Débloque une adresse IP (legacy)."""
        target_ip = ip or kwargs.get("address")
        if not target_ip:
            return {"status": "error", "message": "Missing 'ip' or 'address' parameter"}

        logger.info(f"[OPNsense] Unblocking IP: {target_ip}")

        if self._api_client:
            if self.platform == "linux":
                return await self._api_client.crowdsec_unblock(target_ip)
            elif self.platform == "pfsense":
                return {"status": "success", "ip": target_ip, "message": "PfSense unblock not fully implemented"}

            try:
                result = await self._delete_from_alias("BlockedIPs", target_ip)
                return {"status": "unblocked", "ip": target_ip, "result": result}
            except Exception as e:
                logger.error(f"IP unblock error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "unblocked", "ip": target_ip, "mode": "simulation"}
