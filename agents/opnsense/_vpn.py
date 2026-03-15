"""
Mixin pour la gestion VPN OPNsense — 11 méthodes.

Couvre IPsec (strongSwan) et OpenVPN : consultation des tunnels/instances,
activation/désactivation, sessions actives et déconnexion de clients.
"""

import logging
from typing import Dict

from ._decorators import safety_snapshot

logger = logging.getLogger(__name__)


class VPNMixin:

    # ========================================================================
    # IPsec (strongSwan)
    # ========================================================================

    async def _get_ipsec_status(self) -> Dict:
        """Retourne l'état du service IPsec (strongSwan) sur OPNsense.

        Indique si le daemon IPsec est actif et combien de tunnels sont établis.
        """
        logger.info("[OPNsense] Statut IPsec")
        if self._api_client:
            try:
                return await self._api_client.get_ipsec_status()
            except Exception as e:
                logger.error(f"Erreur statut IPsec: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "unknown", "mode": "simulation"}

    async def _list_ipsec_connections(self) -> Dict:
        """Liste toutes les connexions IPsec configurées (site-to-site, road warrior).

        Retourne les connexions avec leur UUID, nom et état d'activation.
        """
        logger.info("[OPNsense] Liste des connexions IPsec")
        if self._api_client:
            try:
                return await self._api_client.list_ipsec_connections()
            except Exception as e:
                logger.error(f"Erreur liste connexions IPsec: {e}")
                return {"status": "error", "message": str(e)}
        return {"connections": [], "mode": "simulation"}

    @safety_snapshot
    async def _toggle_ipsec_connection(self, uuid: str, enabled: int) -> Dict:
        """Active ou désactive une connexion IPsec par son UUID.

        :param uuid: UUID de la connexion IPsec à modifier.
        :param enabled: 1 pour activer, 0 pour désactiver.
        """
        logger.info(f"[OPNsense] Toggle IPsec {uuid} → {'on' if enabled else 'off'}")
        if self._api_client:
            try:
                response = await self._api_client.toggle_ipsec_connection(uuid, enabled)
                await self._api_client.apply_ipsec_changes()
                return response
            except Exception as e:
                logger.error(f"Erreur toggle IPsec: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "toggled", "uuid": uuid, "enabled": enabled, "mode": "simulation"}

    async def _list_ipsec_sessions(self) -> Dict:
        """Liste les sessions IPsec actives (tunnels phase 1 établis).

        Retourne les sessions actives avec IPs locales/distantes et état.
        """
        logger.info("[OPNsense] Sessions IPsec actives")
        if self._api_client:
            try:
                return await self._api_client.list_ipsec_sessions()
            except Exception as e:
                logger.error(f"Erreur liste sessions IPsec: {e}")
                return {"status": "error", "message": str(e)}
        return {"sessions": [], "mode": "simulation"}

    async def _connect_ipsec_session(self, session_id: str) -> Dict:
        """Établit (initie) une session IPsec par son identifiant.

        :param session_id: Identifiant de la session IPsec à initier.
        """
        logger.info(f"[OPNsense] Connexion session IPsec: {session_id}")
        if self._api_client:
            try:
                return await self._api_client.connect_ipsec_session(session_id)
            except Exception as e:
                logger.error(f"Erreur connexion session IPsec: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "connecting", "session_id": session_id, "mode": "simulation"}

    @safety_snapshot
    async def _disconnect_ipsec_session(self, session_id: str) -> Dict:
        """Déconnecte et ferme une session IPsec active.

        :param session_id: Identifiant de la session IPsec à déconnecter.
        """
        logger.info(f"[OPNsense] Déconnexion session IPsec: {session_id}")
        if self._api_client:
            try:
                return await self._api_client.disconnect_ipsec_session(session_id)
            except Exception as e:
                logger.error(f"Erreur déconnexion session IPsec: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "disconnected", "session_id": session_id, "mode": "simulation"}

    # ========================================================================
    # OpenVPN
    # ========================================================================

    async def _list_openvpn_instances(self) -> Dict:
        """Liste toutes les instances OpenVPN configurées (serveurs et clients).

        Retourne les instances avec leur UUID, description et état d'activation.
        """
        logger.info("[OPNsense] Liste des instances OpenVPN")
        if self._api_client:
            try:
                return await self._api_client.list_openvpn_instances()
            except Exception as e:
                logger.error(f"Erreur liste instances OpenVPN: {e}")
                return {"status": "error", "message": str(e)}
        return {"instances": [], "mode": "simulation"}

    @safety_snapshot
    async def _toggle_openvpn_instance(self, uuid: str, enabled: int) -> Dict:
        """Active ou désactive une instance OpenVPN par son UUID.

        :param uuid: UUID de l'instance OpenVPN à modifier.
        :param enabled: 1 pour activer, 0 pour désactiver.
        """
        logger.info(f"[OPNsense] Toggle OpenVPN {uuid} → {'on' if enabled else 'off'}")
        if self._api_client:
            try:
                response = await self._api_client.toggle_openvpn_instance(uuid, enabled)
                await self._api_client.apply_openvpn_changes()
                return response
            except Exception as e:
                logger.error(f"Erreur toggle OpenVPN: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "toggled", "uuid": uuid, "enabled": enabled, "mode": "simulation"}

    async def _list_openvpn_sessions(self) -> Dict:
        """Liste les sessions OpenVPN actives (clients actuellement connectés).

        Retourne les clients avec leur CN, adresse IP réelle et IP VPN attribuée.
        """
        logger.info("[OPNsense] Sessions OpenVPN actives")
        if self._api_client:
            try:
                return await self._api_client.list_openvpn_sessions()
            except Exception as e:
                logger.error(f"Erreur liste sessions OpenVPN: {e}")
                return {"status": "error", "message": str(e)}
        return {"sessions": [], "mode": "simulation"}

    @safety_snapshot
    async def _kill_openvpn_session(self, common_name: str, address: str) -> Dict:
        """Déconnecte de force un client OpenVPN par son Common Name et adresse.

        :param common_name: Common Name du certificat client OpenVPN (ex: 'user@domain').
        :param address: Adresse IP réelle du client à déconnecter.
        """
        logger.info(f"[OPNsense] Kill session OpenVPN: {common_name} @ {address}")
        if self._api_client:
            try:
                return await self._api_client.kill_openvpn_session(common_name, address)
            except Exception as e:
                logger.error(f"Erreur kill session OpenVPN: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "killed", "common_name": common_name, "mode": "simulation"}
