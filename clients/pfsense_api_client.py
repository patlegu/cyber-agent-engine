# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Client API pour firewall pfSense.

Ce client hérite d'OPNsenseAPIClient car pfSense et OPNsense partagent
environ 80-90% de leur API (OPNsense est un fork de pfSense).

Principales différences :
- Endpoints : /api/v1/ ou /api/v2/ au lieu de /api/
- Noms de champs : 'descr' au lieu de 'description'
- Quelques endpoints spécifiques à pfSense
"""

import logging
from typing import Dict, Optional, List

from .opnsense_api_client import OPNsenseAPIClient

logger = logging.getLogger(__name__)


class PfSenseAPIClient(OPNsenseAPIClient):
    """
    Client API pour pfSense.
    
    Hérite d'OPNsenseAPIClient et adapte les différences :
    - Version API (v1 ou v2)
    - Noms de champs différents
    - Endpoints spécifiques
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str = "",
        api_version: str = "v1",
        verify_ssl: bool = True,
        timeout: int = 30
    ):
        """
        Initialise le client API pfSense.

        Args:
            base_url: URL de base du pfSense (ex: https://192.168.1.1)
            api_key: Clé API (pour pfREST, c'est le token)
            api_secret: Secret API (vide pour pfREST)
            api_version: Version de l'API ("v1" ou "v2", défaut: "v1")
            verify_ssl: Vérifier les certificats SSL
            timeout: Timeout des requêtes en secondes
        """
        super().__init__(base_url, api_key, api_secret, verify_ssl, timeout)
        self.api_version = api_version
        self.use_bearer_auth = not api_secret  # pfREST n'utilise pas de secret
        logger.info(f"pfSense API client initialized (version: {api_version}, auth: {'Bearer' if self.use_bearer_auth else 'Basic'})")

    def _build_url(self, endpoint: str) -> str:
        """
        Construit l'URL complète pour un endpoint.
        
        pfSense utilise /api/v1/ ou /api/v2/ au lieu de /api/
        
        Args:
            endpoint: Endpoint de l'API (ex: /firewall/filter/get)
            
        Returns:
            URL complète
        """
        # Retirer le / initial si présent
        endpoint = endpoint.lstrip('/')
        
        # Construire l'URL avec la version
        return f"{self.base_url}/api/{self.api_version}/{endpoint}"

    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """
        Effectue une requête HTTP vers l'API.
        
        Override pour supporter l'authentification pfREST (Bearer token).
        
        Args:
            method: Méthode HTTP (GET, POST, etc.)
            endpoint: Endpoint de l'API
            **kwargs: Arguments supplémentaires pour httpx
            
        Returns:
            Réponse JSON de l'API
        """
        # Pour pfSense, ne pas utiliser _build_url car il ajoute déjà /api/v2/
        # L'endpoint vient d'OPNsense avec /api/ donc on le retire
        if endpoint.startswith('/api/'):
            endpoint = endpoint[5:]  # Retire '/api/'
        
        url = self._build_url(endpoint)
        
        # Préparer les headers
        headers = kwargs.pop('headers', {})
        
        if self.use_bearer_auth:
            # pfREST utilise Bearer token (sans le mot "Bearer")
            headers['Authorization'] = self.api_key
        else:
            # Authentification Basic (fallback)
            kwargs['auth'] = (self.api_key, self.api_secret)
        
        # Ajouter les headers
        kwargs['headers'] = headers
        
        try:
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else {}
        except Exception as e:
            logger.error(f"Request error {method} {url}: {e}")
            raise

    # ========================================================================
    # Adaptations spécifiques pfSense
    # ========================================================================

    async def add_filter_rule(self, rule_data: Dict) -> Dict:
        """
        Ajoute une règle de filtrage.
        
        ADAPTATION pfSense :
        - Utilise 'descr' au lieu de 'description'
        - Endpoint peut être légèrement différent selon la version
        """
        # Adapter les noms de champs
        if 'rule' in rule_data and 'description' in rule_data['rule']:
            rule_data['rule']['descr'] = rule_data['rule'].pop('description')
        
        # Appeler la méthode parente
        return await super().add_filter_rule(rule_data)

    async def update_filter_rule(self, uuid: str, rule_data: Dict) -> Dict:
        """
        Modifie une règle de filtrage.
        
        ADAPTATION pfSense :
        - Utilise 'descr' au lieu de 'description'
        """
        # Adapter les noms de champs
        if 'rule' in rule_data and 'description' in rule_data['rule']:
            rule_data['rule']['descr'] = rule_data['rule'].pop('description')
        
        return await super().update_filter_rule(uuid, rule_data)

    async def add_alias(self, alias_data: Dict) -> Dict:
        """
        Ajoute un alias.
        
        ADAPTATION pfSense :
        - Utilise 'descr' au lieu de 'description'
        - Format de contenu peut différer
        """
        # Adapter les noms de champs
        if 'alias' in alias_data and 'description' in alias_data['alias']:
            alias_data['alias']['descr'] = alias_data['alias'].pop('description')
        
        return await super().add_alias(alias_data)

    async def update_alias(self, uuid: str, alias_data: Dict) -> Dict:
        """
        Modifie un alias.
        
        ADAPTATION pfSense :
        - Utilise 'descr' au lieu de 'description'
        """
        # Adapter les noms de champs
        if 'alias' in alias_data and 'description' in alias_data['alias']:
            alias_data['alias']['descr'] = alias_data['alias'].pop('description')
        
        return await super().update_alias(uuid, alias_data)

    # ========================================================================
    # Méthodes spécifiques pfSense (non présentes dans OPNsense)
    # ========================================================================

    async def get_system_info(self) -> Dict:
        """
        Récupère les informations système de pfSense.
        
        Endpoint spécifique à pfSense.
        """
        return await self._request('GET', '/system/info')

    async def get_packages(self) -> Dict:
        """
        Liste les packages installés.
        
        Endpoint spécifique à pfSense.
        """
        return await self._request('GET', '/system/packages')

    async def install_package(self, package_name: str) -> Dict:
        """
        Installe un package pfSense.
        
        Args:
            package_name: Nom du package à installer
            
        Returns:
            Résultat de l'installation
        """
        data = {"package": package_name}
        return await self._request('POST', '/system/packages/install', json=data)

    async def get_interfaces_assignment(self) -> Dict:
        """
        Récupère l'assignation des interfaces.
        
        Format peut différer d'OPNsense.
        """
        return await self._request('GET', '/interfaces/assignment')

    # ========================================================================
    # Méthodes de compatibilité
    # ========================================================================

    async def test_connection(self) -> bool:
        """
        Teste la connexion à l'API pfSense.
        
        Returns:
            True si la connexion fonctionne, False sinon
        """
        try:
            # Tester avec un endpoint simple
            response = await self.get_system_info()
            
            if response and 'platform' in response:
                logger.info(f"✓ Connexion pfSense OK - Platform: {response.get('platform')}")
                return True
            
            # Fallback sur la méthode parente
            return await super().test_connection()
            
        except Exception as e:
            logger.error(f"✗ Erreur de connexion pfSense: {e}")
            return False

    def get_api_version_info(self) -> Dict:
        """
        Récupère les informations sur la version de l'API.
        
        Returns:
            Informations de version
        """
        try:
            info = self.get_system_info()
            return {
                "api_version": self.api_version,
                "platform": info.get('platform', 'unknown'),
                "version": info.get('version', 'unknown'),
                "base_url": self.base_url
            }
        except Exception as e:
            logger.error(f"Version retrieval error: {e}")
            return {
                "api_version": self.api_version,
                "error": str(e)
            }


# ============================================================================
# Fonctions utilitaires
# ============================================================================

def create_pfsense_client(config: Dict) -> PfSenseAPIClient:
    """
    Crée un client API pfSense à partir d'une configuration.
    
    Args:
        config: Dictionnaire de configuration avec :
            - base_url: URL du pfSense
            - api_key: Clé API
            - api_secret: Secret API
            - api_version: Version API (optionnel, défaut: "v1")
            - verify_ssl: Vérifier SSL (optionnel, défaut: True)
            - timeout: Timeout (optionnel, défaut: 30)
    
    Returns:
        Instance de PfSenseAPIClient
    
    Example:
        >>> from config.pfsense_config import PFSENSE_CONFIG
        >>> client = create_pfsense_client(PFSENSE_CONFIG)
        >>> client.test_connection()
    """
    return PfSenseAPIClient(
        base_url=config['base_url'],
        api_key=config['api_key'],
        api_secret=config['api_secret'],
        api_version=config.get('api_version', 'v1'),
        verify_ssl=config.get('verify_ssl', True),
        timeout=config.get('timeout', 30)
    )
