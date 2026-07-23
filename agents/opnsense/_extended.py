# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Fonctions étendues : Organisation, GeoIP, Firmware, DNS/DHCP — 14 méthodes.
"""

import logging
from typing import Dict

from ._decorators import safety_snapshot

logger = logging.getLogger(__name__)


class ExtendedMixin:

    # --- Organisation ---

    @safety_snapshot
    async def _create_category(self, name: str, **kwargs) -> Dict:
        """Crée une catégorie pour organiser les règles."""
        logger.info(f"[OPNsense] Creating category: {name}")

        if self._api_client:
            try:
                cat_data = {"category": {"name": name, **{k: v for k, v in kwargs.items() if v is not None}}}
                response = await self._api_client.create_category(cat_data)
                if response.get('result') == 'saved':
                    await self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Category '{name}' created")
                return response
            except Exception as e:
                logger.error(f"Category creation error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "created", "uuid": f"cat-{hash(name) % 10000}", "mode": "simulation"}

    @safety_snapshot
    async def _delete_category(self, uuid: str) -> Dict:
        """Supprime une catégorie."""
        logger.info(f"[OPNsense] Removing category: {uuid}")

        if self._api_client:
            try:
                response = await self._api_client.delete_category(uuid)
                if response.get('result') == 'deleted':
                    await self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Category {uuid} removed")
                return response
            except Exception as e:
                logger.error(f"Category removal error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "deleted", "uuid": uuid, "mode": "simulation"}

    async def _list_available_categories(self) -> Dict:
        """Liste toutes les catégories disponibles."""
        logger.info("[OPNsense] Listing categories")

        if self._api_client:
            try:
                return await self._api_client.list_available_categories()
            except Exception as e:
                logger.error(f"Category list error: {e}")
                return {"status": "error", "message": str(e)}

        return {"categories": [], "mode": "simulation"}

    @safety_snapshot
    async def _update_bogons(self) -> Dict:
        """Met à jour les listes de réseaux bogons."""
        logger.info("[OPNsense] Updating bogons")

        if self._api_client:
            try:
                response = await self._api_client.update_bogons()
                logger.info("✓ Bogons updated")
                return response
            except Exception as e:
                logger.error(f"Bogons update error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "updated", "mode": "simulation"}

    # --- GeoIP ---

    async def _list_geoip_countries(self) -> Dict:
        """Liste tous les pays disponibles pour GeoIP."""
        logger.info("[OPNsense] Listing GeoIP countries")

        if self._api_client:
            try:
                return await self._api_client.list_geoip_countries()
            except Exception as e:
                logger.error(f"GeoIP country list error: {e}")
                return {"status": "error", "message": str(e)}

        return {"countries": ["FR", "US", "DE", "GB", "CN", "RU"], "mode": "simulation"}

    async def _get_geoip_database(self) -> Dict:
        """Récupère les informations sur la base GeoIP."""
        logger.info("[OPNsense] GeoIP database info")

        if self._api_client:
            try:
                return await self._api_client.get_geoip_database()
            except Exception as e:
                logger.error(f"GeoIP database info error: {e}")
                return {"status": "error", "message": str(e)}

        return {"version": "2024.01", "last_update": "2024-01-15", "mode": "simulation"}

    # --- Firmware & Updates ---

    async def _check_updates(self) -> Dict:
        """Vérifie la disponibilité des mises à jour du système."""
        logger.info("[OPNsense] Checking updates")

        if self._api_client:
            try:
                import asyncio
                await self._api_client.check_updates()
                await asyncio.sleep(2)
                return await self._api_client.get_upgrade_status()
            except Exception as e:
                logger.error(f"Update check error: {e}")
                return {"status": "error", "message": str(e)}

        return {
            "status": "ok",
            "new_packages": [{"name": "os-firewall", "version": "1.0", "new_version": "1.1"}],
            "mode": "simulation"
        }

    async def _get_upgrade_status(self) -> Dict:
        """Récupère le statut d'une mise à jour en cours."""
        logger.info("[OPNsense] Upgrade status")

        if self._api_client:
            try:
                return await self._api_client.get_upgrade_status()
            except Exception as e:
                logger.error(f"Upgrade status error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "done", "log": ["Upgrade finished successfully"], "mode": "simulation"}

    @safety_snapshot
    async def _upgrade_firmware(self, upgrade_type: str = "pkg") -> Dict:
        """Lance une mise à jour du système. ATTENTION: peut redémarrer le firewall."""
        logger.info(f"[OPNsense] Launching upgrade ({upgrade_type})")

        if self._api_client:
            try:
                response = await self._api_client.upgrade_firmware(upgrade_type)
                logger.warning("⚠ Upgrade launched. The system may reboot.")
                return response
            except Exception as e:
                logger.error(f"Upgrade launch error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "running", "upgrade_type": upgrade_type, "mode": "simulation"}

    # --- Network Services (DNS / DHCP) ---

    @safety_snapshot
    async def _add_dns_override(self, hostname: str, domain: str, ip: str, description: str = "") -> Dict:
        """Ajoute un DNS Host Override (enregistrement A) dans Unbound."""
        logger.info(f"[OPNsense] Adding DNS Override: {hostname}.{domain} -> {ip}")

        if self._api_client:
            try:
                res = await self._api_client.add_dns_override(hostname, domain, ip, description)
                await self._api_client.reconfigure_unbound()
                return res
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {"status": "added", "record": f"{hostname}.{domain} -> {ip}", "mode": "simulation"}

    async def _list_dns_overrides(self) -> Dict:
        """Liste tous les DNS Host Overrides Unbound."""
        if self._api_client:
            try:
                return await self._api_client.search_dns_overrides()
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {"rows": [{"hostname": "test", "domain": "local", "server": "1.2.3.4"}], "mode": "simulation"}

    async def _delete_dns_override(self, hostname: str, domain: str) -> Dict:
        """Supprime un DNS Host Override Unbound."""
        logger.info(f"[OPNsense] Removing DNS Override: {hostname}.{domain}")

        if self._api_client:
            try:
                overrides = await self._api_client.search_dns_overrides()
                target_uuid = None
                if 'rows' in overrides:
                    for row in overrides['rows']:
                        if row.get('hostname') == hostname and row.get('domain') == domain:
                            target_uuid = row.get('uuid')
                            break

                if target_uuid:
                    res = await self._api_client.delete_dns_override(target_uuid)
                    await self._api_client.reconfigure_unbound()
                    return res
                return {"status": "error", "message": "DNS record not found"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {"status": "deleted", "record": f"{hostname}.{domain}", "mode": "simulation"}

    @safety_snapshot
    async def _manage_dns_blocklist(self, enabled: int = 1, force_download: bool = False) -> Dict:
        """Active ou désactive la liste de blocage DNS Unbound (DNSBL)."""
        logger.info(f"[OPNsense] Managing Unbound DNS Blocklist (enabled={enabled})")
        
        if self._api_client:
            try:
                return await self._api_client.manage_dns_blocklist(enabled, force_download)
            except Exception as e:
                return {"status": "error", "message": str(e)}
                
        return {"status": "success", "enabled": enabled, "mode": "simulation"}

    async def _search_dns_queries(self, search_phrase: str = "", limit: int = 100) -> Dict:
        """Recherche dans l'historique des requêtes DNS Unbound."""
        logger.info(f"[OPNsense] Searching DNS queries: '{search_phrase}'")
        
        if self._api_client:
            try:
                return await self._api_client.search_dns_queries(search_phrase, limit)
            except Exception as e:
                return {"status": "error", "message": str(e)}
                
        return {"rows": [{"domain": "example.com", "action": "Pass", "source": "192.168.1.5"}], "mode": "simulation"}

    async def _get_dhcp_leases(self) -> Dict:
        """Récupère les baux DHCPv4 actifs."""
        if self._api_client:
            try:
                return await self._api_client.get_dhcp_leases()
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {"rows": [{"address": "192.168.1.100", "mac": "aa:bb:cc:dd:ee:ff", "hostname": "iphone"}], "mode": "simulation"}

    @safety_snapshot
    async def _add_static_mapping(self, mac: str, ip: str, hostname: str, description: str = "") -> Dict:
        """Ajoute une réservation DHCP statique."""
        logger.info(f"[OPNsense] Adding DHCP Static: {mac} -> {ip} ({hostname})")

        if self._api_client:
            try:
                return await self._api_client.add_static_mapping(mac, ip, hostname, description)
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {"status": "added", "mapping": f"{mac} -> {ip}", "mode": "simulation"}

    # ========================================================================
    # Lot 3 — ACME / Certificats Let's Encrypt
    # ========================================================================

    async def _get_acme_status(self) -> Dict:
        """Retourne l'état du service ACME client (plugin Let's Encrypt OPNsense).

        Vérifie si le plugin ACME est installé et en cours d'exécution.
        """
        logger.info("[OPNsense] ACME client status")
        if self._api_client:
            try:
                return await self._api_client.get_acme_status()
            except Exception as e:
                logger.error(f"ACME status error: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "unknown", "mode": "simulation"}

    async def _list_acme_certificates(self) -> Dict:
        """Liste tous les certificats TLS gérés par le client ACME (Let's Encrypt).

        Retourne les certificats, leurs domaines et dates d'expiration.
        """
        logger.info("[OPNsense] Listing ACME certificates")
        if self._api_client:
            try:
                return await self._api_client.list_acme_certificates()
            except Exception as e:
                logger.error(f"ACME certificate list error: {e}")
                return {"status": "error", "message": str(e)}
        return {"certificates": [], "mode": "simulation"}

    async def _sign_acme_certificate(self, uuid: str) -> Dict:
        """Déclenche la demande ou le renouvellement d'un certificat Let's Encrypt.

        :param uuid: UUID du certificat ACME à signer/renouveler.
        """
        logger.info(f"[OPNsense] Signing ACME certificate: {uuid}")
        if self._api_client:
            try:
                return await self._api_client.sign_acme_certificate(uuid)
            except Exception as e:
                logger.error(f"ACME certificate signing error: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "signed", "uuid": uuid, "mode": "simulation"}

    async def _update_acme_certificate(self, uuid: str) -> Dict:
        """Force la mise à jour d'un certificat ACME existant (re-challenge ACME).

        :param uuid: UUID du certificat ACME à mettre à jour.
        """
        logger.info(f"[OPNsense] Updating ACME certificate: {uuid}")
        if self._api_client:
            try:
                return await self._api_client.update_acme_certificate(uuid)
            except Exception as e:
                logger.error(f"ACME certificate update error: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "updated", "uuid": uuid, "mode": "simulation"}

    async def _revoke_acme_certificate(self, uuid: str) -> Dict:
        """Révoque un certificat ACME auprès de l'autorité de certification.

        :param uuid: UUID du certificat ACME à révoquer.
        """
        logger.info(f"[OPNsense] Revoking ACME certificate: {uuid}")
        if self._api_client:
            try:
                return await self._api_client.revoke_acme_certificate(uuid)
            except Exception as e:
                logger.error(f"ACME certificate revocation error: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "revoked", "uuid": uuid, "mode": "simulation"}

    async def _list_acme_accounts(self) -> Dict:
        """Liste les comptes ACME (Let's Encrypt) configurés sur OPNsense.

        Chaque compte correspond à une adresse email d'enregistrement ACME.
        """
        logger.info("[OPNsense] Listing ACME accounts")
        if self._api_client:
            try:
                return await self._api_client.list_acme_accounts()
            except Exception as e:
                logger.error(f"ACME account list error: {e}")
                return {"status": "error", "message": str(e)}
        return {"accounts": [], "mode": "simulation"}
