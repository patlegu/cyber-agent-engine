# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Règles NAT — 5 méthodes.
"""

import logging
from typing import Dict

from ._decorators import safety_snapshot

logger = logging.getLogger(__name__)


class NATMixin:

    @safety_snapshot
    async def _create_nat_outbound(self, interface: str, source: str, **kwargs) -> Dict:
        """Crée une règle NAT sortant (masquerading)."""
        logger.info(f"[OPNsense] Création NAT sortant: {source} via {interface}")

        if self._api_client:
            try:
                nat_data = {
                    "nat": {
                        "interface": interface,
                        "source": source,
                        **{k: v for k, v in kwargs.items() if v is not None}
                    }
                }
                response = await self._api_client.add_nat_outbound(nat_data)
                if response.get('result') == 'saved':
                    await self._api_client.apply_firewall_changes()
                    logger.info("✓ NAT sortant créé")
                return response
            except Exception as e:
                logger.error(f"Erreur création NAT sortant: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "created", "uuid": f"nat-out-{hash(source) % 10000}", "mode": "simulation"}

    @safety_snapshot
    async def _delete_nat_outbound(self, uuid: str) -> Dict:
        """Supprime une règle NAT sortant."""
        logger.info(f"[OPNsense] Suppression NAT sortant: {uuid}")

        if self._api_client:
            try:
                response = await self._api_client.delete_nat_outbound(uuid)
                if response.get('result') == 'deleted':
                    await self._api_client.apply_firewall_changes()
                    logger.info(f"✓ NAT sortant {uuid} supprimé")
                return response
            except Exception as e:
                logger.error(f"Erreur suppression NAT sortant: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "deleted", "uuid": uuid, "mode": "simulation"}

    @safety_snapshot
    async def _create_nat_port_forward(
        self,
        interface: str,
        protocol: str,
        destination_port: str,
        redirect_target_ip: str,
        redirect_target_port: str,
        **kwargs
    ) -> Dict:
        """Crée une redirection de port."""
        logger.info(f"[OPNsense] Port forward: {destination_port} -> {redirect_target_ip}:{redirect_target_port}")

        if self._api_client:
            try:
                pf_data = {
                    "nat": {
                        "interface": interface,
                        "protocol": protocol,
                        "destination_port": destination_port,
                        "redirect_target_ip": redirect_target_ip,
                        "redirect_target_port": redirect_target_port,
                        **{k: v for k, v in kwargs.items() if v is not None}
                    }
                }
                response = await self._api_client.add_nat_port_forward(pf_data)
                if response.get('result') == 'saved':
                    await self._api_client.apply_firewall_changes()
                    logger.info("✓ Port forward créé")
                return response
            except Exception as e:
                logger.error(f"Erreur création port forward: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "created", "uuid": f"pf-{hash(destination_port) % 10000}", "mode": "simulation"}

    @safety_snapshot
    async def _create_nat_one_to_one(self, interface: str, external_ip: str, internal_ip: str, **kwargs) -> Dict:
        """Crée un NAT 1:1 (bimap)."""
        logger.info(f"[OPNsense] NAT 1:1: {external_ip} <-> {internal_ip}")

        if self._api_client:
            try:
                nat_data = {
                    "nat": {
                        "interface": interface,
                        "external_ip": external_ip,
                        "internal_ip": internal_ip,
                        **{k: v for k, v in kwargs.items() if v is not None}
                    }
                }
                response = await self._api_client.add_nat_one_to_one(nat_data)
                if response.get('result') == 'saved':
                    await self._api_client.apply_firewall_changes()
                    logger.info("✓ NAT 1:1 créé")
                return response
            except Exception as e:
                logger.error(f"Erreur création NAT 1:1: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "created", "uuid": f"nat1to1-{hash(external_ip) % 10000}", "mode": "simulation"}

    @safety_snapshot
    async def _delete_nat_one_to_one(self, uuid: str) -> Dict:
        """Supprime un NAT 1:1."""
        logger.info(f"[OPNsense] Suppression NAT 1:1: {uuid}")

        if self._api_client:
            try:
                response = await self._api_client.delete_nat_one_to_one(uuid)
                if response.get('result') == 'deleted':
                    await self._api_client.apply_firewall_changes()
                    logger.info(f"✓ NAT 1:1 {uuid} supprimé")
                return response
            except Exception as e:
                logger.error(f"Erreur suppression NAT 1:1: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "deleted", "uuid": uuid, "mode": "simulation"}
