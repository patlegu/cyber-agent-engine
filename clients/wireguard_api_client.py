"""
Client API pour WireGuard sur OPNsense.

Ce client hérite d'OPNsenseAPIClient et ajoute les méthodes spécifiques
pour la gestion complète de WireGuard : serveurs, clients/peers, clés, monitoring.
"""

import logging
from typing import Dict, List, Optional

from .opnsense_api_client import OPNsenseAPIClient

logger = logging.getLogger(__name__)


class WireGuardAPIClient(OPNsenseAPIClient):
    """
    Client API pour WireGuard sur OPNsense.
    
    Gère les serveurs WireGuard, les clients/peers, la génération de clés,
    et le monitoring des tunnels.
    
    Example:
        >>> client = WireGuardAPIClient(
        ...     base_url="https://opnsense.example.com",
        ...     api_key="your-api-key",
        ...     api_secret="your-api-secret"
        ... )
        >>> servers = client.get_wireguard_servers()
    """

    # ========================================================================
    # Gestion des Serveurs WireGuard
    # ========================================================================

    async def get_wireguard_servers(self) -> Dict:
        """
        Liste tous les serveurs WireGuard configurés.
        
        Returns:
            Dictionnaire contenant la liste des serveurs
        """
        return await self._request('GET', '/api/wireguard/server/get')

    async def get_wireguard_server(self, uuid: str) -> Dict:
        """
        Récupère les détails d'un serveur WireGuard spécifique.
        
        Args:
            uuid: UUID du serveur
            
        Returns:
            Détails du serveur
        """
        return await self._request('GET', f'/api/wireguard/server/get_server/{uuid}')

    async def add_wireguard_server(self, server_data: Dict) -> Dict:
        """
        Crée un nouveau serveur WireGuard.
        
        Args:
            server_data: Configuration du serveur
                {
                    "server": {
                        "enabled": "1",
                        "name": "site-a",
                        "pubkey": "...",
                        "privkey": "...",
                        "port": "51820",
                        "tunneladdress": "10.0.0.1/24",
                        "peers": "uuid1,uuid2",
                        "disableroutes": "0"
                    }
                }
                
        Returns:
            Résultat de la création avec UUID
        """
        return await self._request('POST', '/api/wireguard/server/add_server', data=server_data)

    async def update_wireguard_server(self, uuid: str, server_data: Dict) -> Dict:
        """
        Met à jour un serveur WireGuard existant.
        
        Args:
            uuid: UUID du serveur
            server_data: Nouvelles données du serveur
            
        Returns:
            Résultat de la mise à jour
        """
        return await self._request('POST', f'/api/wireguard/server/set_server/{uuid}', data=server_data)

    async def delete_wireguard_server(self, uuid: str) -> Dict:
        """
        Supprime un serveur WireGuard.
        
        Args:
            uuid: UUID du serveur à supprimer
            
        Returns:
            Résultat de la suppression
        """
        return await self._request('POST', f'/api/wireguard/server/del_server/{uuid}')

    async def toggle_wireguard_server(self, uuid: str, enabled: Optional[bool] = None) -> Dict:
        """
        Active ou désactive un serveur WireGuard.
        
        Args:
            uuid: UUID du serveur
            enabled: True pour activer, False pour désactiver, None pour toggle
            
        Returns:
            Résultat du toggle
        """
        data = {}
        if enabled is not None:
            data['enabled'] = '1' if enabled else '0'
        return await self._request('POST', f'/api/wireguard/server/toggle_server/{uuid}', data=data)

    # ========================================================================
    # Gestion des Clients/Peers WireGuard
    # ========================================================================

    async def get_wireguard_clients(self) -> Dict:
        """
        Liste tous les clients/peers WireGuard configurés.
        
        Returns:
            Dictionnaire contenant la liste des clients
        """
        return await self._request('GET', '/api/wireguard/client/get')

    async def get_wireguard_client(self, uuid: str) -> Dict:
        """
        Récupère les détails d'un client/peer WireGuard spécifique.
        
        Args:
            uuid: UUID du client
            
        Returns:
            Détails du client
        """
        return await self._request('GET', f'/api/wireguard/client/get_client/{uuid}')

    async def add_wireguard_client(self, client_data: Dict) -> Dict:
        """
        Ajoute un nouveau client/peer WireGuard.
        
        Args:
            client_data: Configuration du client
                {
                    "client": {
                        "enabled": "1",
                        "name": "site-b",
                        "pubkey": "...",
                        "psk": "...",  # Pre-shared key (optionnel)
                        "tunneladdress": "10.0.0.2/32",
                        "serveraddress": "",
                        "serverport": "",
                        "keepalive": "25"
                    }
                }
                
        Returns:
            Résultat de la création avec UUID
        """
        return await self._request('POST', '/api/wireguard/client/add_client', data=client_data)

    async def update_wireguard_client(self, uuid: str, client_data: Dict) -> Dict:
        """
        Met à jour un client/peer WireGuard existant.
        
        Args:
            uuid: UUID du client
            client_data: Nouvelles données du client
            
        Returns:
            Résultat de la mise à jour
        """
        return await self._request('POST', f'/api/wireguard/client/set_client/{uuid}', data=client_data)

    async def delete_wireguard_client(self, uuid: str) -> Dict:
        """
        Supprime un client/peer WireGuard.
        
        Args:
            uuid: UUID du client à supprimer
            
        Returns:
            Résultat de la suppression
        """
        return await self._request('POST', f'/api/wireguard/client/del_client/{uuid}')

    async def toggle_wireguard_client(self, uuid: str, enabled: Optional[bool] = None) -> Dict:
        """
        Active ou désactive un client/peer WireGuard.
        
        Args:
            uuid: UUID du client
            enabled: True pour activer, False pour désactiver, None pour toggle
            
        Returns:
            Résultat du toggle
        """
        data = {}
        if enabled is not None:
            data['enabled'] = '1' if enabled else '0'
        return await self._request('POST', f'/api/wireguard/client/toggle_client/{uuid}', data=data)

    # ========================================================================
    # Génération de Clés
    # ========================================================================

    async def generate_wireguard_keypair(self) -> Dict:
        """
        Génère une nouvelle paire de clés WireGuard (publique/privée).
        
        Returns:
            Dictionnaire avec 'pubkey' et 'privkey'
        """
        return await self._request('GET', '/api/wireguard/server/key_pair')

    async def generate_wireguard_psk(self) -> Dict:
        """
        Génère une nouvelle pre-shared key (PSK) WireGuard.
        
        Returns:
            Dictionnaire avec 'psk'
        """
        return await self._request('GET', '/api/wireguard/client/psk')

    # ========================================================================
    # Configuration Générale
    # ========================================================================

    async def get_wireguard_general_config(self) -> Dict:
        """
        Récupère la configuration générale de WireGuard.
        
        Returns:
            Configuration générale
        """
        return await self._request('GET', '/api/wireguard/general/get')

    async def set_wireguard_general_config(self, config_data: Dict) -> Dict:
        """
        Met à jour la configuration générale de WireGuard.
        
        Args:
            config_data: Nouvelle configuration générale
            
        Returns:
            Résultat de la mise à jour
        """
        return await self._request('POST', '/api/wireguard/general/set', data=config_data)

    # ========================================================================
    # Contrôle du Service
    # ========================================================================

    async def reconfigure_wireguard(self) -> Dict:
        """
        Reconfigure le service WireGuard (applique les changements).
        
        Returns:
            Résultat de la reconfiguration
        """
        return await self._request('POST', '/api/wireguard/service/reconfigure')

    async def restart_wireguard(self) -> Dict:
        """
        Redémarre le service WireGuard.
        
        Returns:
            Résultat du redémarrage
        """
        return await self._request('POST', '/api/wireguard/service/restart')

    async def get_wireguard_status(self) -> Dict:
        """
        Récupère le statut actuel de WireGuard.
        
        Inclut les informations sur les tunnels actifs, handshakes, etc.
        
        Returns:
            Statut détaillé de WireGuard
        """
        return await self._request('GET', '/api/wireguard/service/show')

    # ========================================================================
    # Méthodes Utilitaires
    # ========================================================================

    async def list_servers_for_client(self) -> Dict:
        """
        Liste les serveurs disponibles pour un client.
        
        Returns:
            Liste des serveurs disponibles
        """
        return await self._request('GET', '/api/wireguard/client/list_servers')

    async def get_server_info_for_client(self, server_uuid: str) -> Dict:
        """
        Récupère les informations d'un serveur pour configuration client.
        
        Args:
            server_uuid: UUID du serveur
            
        Returns:
            Informations du serveur (endpoint, port, clé publique)
        """
        return await self._request('GET', f'/api/wireguard/client/get_server_info/{server_uuid}')


# ============================================================================
# Fonction utilitaire
# ============================================================================

def create_wireguard_client(config: Dict) -> WireGuardAPIClient:
    """
    Crée un client API WireGuard à partir d'une configuration.
    
    Args:
        config: Dictionnaire de configuration avec :
            - base_url: URL d'OPNsense
            - api_key: Clé API
            - api_secret: Secret API
            - verify_ssl: Vérifier SSL (optionnel)
            - timeout: Timeout (optionnel)
    
    Returns:
        Instance de WireGuardAPIClient
    
    Example:
        >>> from config.opnsense_config import OPNSENSE_CONFIG
        >>> client = create_wireguard_client(OPNSENSE_CONFIG)
        >>> servers = client.get_wireguard_servers()
    """
    return WireGuardAPIClient(
        base_url=config['base_url'],
        api_key=config['api_key'],
        api_secret=config['api_secret'],
        verify_ssl=config.get('verify_ssl', True),
        timeout=config.get('timeout', 30)
    )
