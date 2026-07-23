# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Client API pour OPNsense Firewall.

Ce module implémente un client complet pour l'API REST d'OPNsense,
couvrant toutes les fonctionnalités du firewall.

Documentation API: https://docs.opnsense.org/development/api.html
"""

import logging
import httpx
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin
import json

logger = logging.getLogger(__name__)


class OPNsenseAPIError(Exception):
    """Exception levée lors d'erreurs API OPNsense."""
    pass


class OPNsenseAPIClient:
    """
    Client pour l'API REST OPNsense.
    
    Authentification via API key + secret.
    
    Example:
        >>> client = OPNsenseAPIClient(
        ...     base_url="https://opnsense.example.com",
        ...     api_key="your-api-key",
        ...     api_secret="your-api-secret"
        ... )
        >>> rules = client.get_filter_rules()
    """
    
    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        verify_ssl: bool = True,
        timeout: int = 30
    ):
        """
        Initialise le client API OPNsense.
        
        Args:
            base_url: URL de base OPNsense (ex: https://192.168.1.1)
            api_key: Clé API
            api_secret: Secret API
            verify_ssl: Vérifier les certificats SSL
            timeout: Timeout des requêtes en secondes
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.api_secret = api_secret
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            auth=(api_key, api_secret),
            verify=verify_ssl,
            timeout=timeout
        )
        
        logger.info(f"OPNsense API client initialized: {base_url}")
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        suppress_log_404: bool = False
    ) -> Dict:
        """
        Effectue une requête HTTP vers l'API OPNsense.
        
        Args:
            method: Méthode HTTP (GET, POST, DELETE, etc.)
            endpoint: Endpoint API (ex: /api/firewall/filter/addRule)
            data: Données à envoyer (pour POST/PUT)
            params: Paramètres URL (pour GET)
            suppress_log_404: Si True, ne logue pas d'erreur pour les 404 (utile pour les fallbacks)
            
        Returns:
            Réponse JSON de l'API
            
        Raises:
            OPNsenseAPIError: En cas d'erreur API
        """
        url = urljoin(self.base_url, endpoint)
        
        try:
            response = await self.client.request(
                method=method,
                url=endpoint,  # httpx.AsyncClient uses base_url if set
                json=data,
                params=params
            )
            
            response.raise_for_status()
            
            # OPNsense retourne toujours du JSON
            return response.json()
            
        except httpx.HTTPStatusError as e:
            if not (suppress_log_404 and e.response.status_code == 404):
                logger.error(f"HTTP Error: {e}")
            raise OPNsenseAPIError(f"HTTP {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"Request Error: {e}")
            raise OPNsenseAPIError(f"Request failed: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON Decode Error: {e}")
            raise OPNsenseAPIError(f"Invalid JSON response: {str(e)}")
    
    # ========================================================================
    # Règles de filtrage
    # ========================================================================
    
    async def add_filter_rule(self, rule_data: Dict) -> Dict:
        """
        Crée une nouvelle règle de filtrage.
        
        Args:
            rule_data: Données de la règle (description, interface, protocol, etc.)
            
        Returns:
            Réponse API avec UUID de la règle créée
        """
        return await self._request('POST', '/api/firewall/filter/addRule', data=rule_data)
    
    async def get_filter_rule(self, uuid: Optional[str] = None) -> Dict:
        """
        Récupère une ou toutes les règles de filtrage.
        
        Args:
            uuid: UUID de la règle (optionnel, retourne toutes si omis)
            
        Returns:
            Règle(s) de filtrage
        """
        if uuid:
            return await self._request('GET', f'/api/firewall/filter/getRule/{uuid}')
        else:
            return await self._request('GET', '/api/firewall/filter/get')
    
    async def set_filter_rule(self, uuid: str, rule_data: Dict) -> Dict:
        """
        Modifie une règle de filtrage existante.
        
        Args:
            uuid: UUID de la règle
            rule_data: Nouvelles données de la règle
            
        Returns:
            Réponse API
        """
        return await self._request('POST', f'/api/firewall/filter/setRule/{uuid}', data=rule_data)
    
    async def delete_filter_rule(self, uuid: str) -> Dict:
        """
        Supprime une règle de filtrage.
        
        Args:
            uuid: UUID de la règle
            
        Returns:
            Réponse API
        """
        return await self._request('POST', f'/api/firewall/filter/delRule/{uuid}')
    
    async def toggle_filter_rule(self, uuid: str, enabled: Optional[int] = None) -> Dict:
        """
        Active/désactive une règle de filtrage.
        
        Args:
            uuid: UUID de la règle
            enabled: 1 pour activer, 0 pour désactiver (toggle si omis)
            
        Returns:
            Réponse API
        """
        endpoint = f'/api/firewall/filter/toggleRule/{uuid}'
        if enabled is not None:
            endpoint += f'/{enabled}'
        return await self._request('POST', endpoint)
    
    # ========================================================================
    # Alias
    # ========================================================================
    
    async def add_alias(self, alias_data: Dict) -> Dict:
        """
        Crée un nouvel alias.
        
        Args:
            alias_data: Données de l'alias (name, type, content, etc.)
            
        Returns:
            Réponse API avec UUID de l'alias créé
        """
        return await self._request('POST', '/api/firewall/alias/addItem', data=alias_data)
    
    async def get_alias(self, uuid: Optional[str] = None) -> Dict:
        """
        Récupère un ou tous les alias.
        
        Args:
            uuid: UUID de l'alias (optionnel)
            
        Returns:
            Alias
        """
        if uuid:
            return await self._request('GET', f'/api/firewall/alias/getItem/{uuid}')
        else:
            return await self._request('GET', '/api/firewall/alias/get')
    
    async def set_alias(self, uuid: str, alias_data: Dict) -> Dict:
        """
        Modifie un alias existant.
        
        Args:
            uuid: UUID de l'alias
            alias_data: Nouvelles données
            
        Returns:
            Réponse API
        """
        return await self._request('POST', f'/api/firewall/alias/setItem/{uuid}', data=alias_data)
    
    async def delete_alias(self, uuid: str) -> Dict:
        """
        Supprime un alias.
        
        Args:
            uuid: UUID de l'alias
            
        Returns:
            Réponse API
        """
        return await self._request('POST', f'/api/firewall/alias/delItem/{uuid}')
    
    async def get_alias_uuid(self, name: str) -> Optional[str]:
        """
        Récupère l'UUID d'un alias par son nom.
        """
        try:
            # Essaie l'endpoint direct s'il existe
            response = await self._request('GET', f'/api/firewall/alias/getAliasUUID/{name}')
            if isinstance(response, dict) and 'uuid' in response:
                return response['uuid']
                
            # Fallback: Récupération de tous les alias
            all_aliases = await self.get_alias()
            
            # Diagnostic structure observed: all_aliases['list']['aliases']['alias'] = { uuid: { name: name, ... } }
            aliases_dict = {}
            try:
                if 'list' in all_aliases and 'aliases' in all_aliases['list']:
                    aliases_dict = all_aliases['list']['aliases'].get('alias', {})
                elif 'alias' in all_aliases and 'aliases' in all_aliases['alias']:
                    aliases_dict = all_aliases['alias']['aliases'].get('alias', {})
            except:
                pass
            
            if isinstance(aliases_dict, dict):
                for uuid, data in aliases_dict.items():
                    if isinstance(data, dict) and data.get('name') == name:
                        return uuid
                    
        except Exception:
            pass
        return None

    async def add_to_alias(self, alias_name: str, address: str) -> Dict:
        """
        Ajoute une entrée à un alias via l'utilitaire atomique.
        
        Note: Utilise /api/firewall/alias_util/add
        """
        data = {"address": address}
        res = await self._request('POST', f'/api/firewall/alias_util/add/{alias_name}', data=data)
        
        # OPNsense alias_util doesn't require a full reconfigure for dynamic aliases (external/host),
        # but for consistency with existing logic and to ensure PF table update:
        if res.get('result') == 'added' or res.get('status') == 'success':
             await self.reconfigure_alias()
             
        return res

    async def delete_from_alias(self, alias_name: str, address: str) -> Dict:
        """
        Retire une entrée d'un alias via l'utilitaire atomique.
        
        Note: Utilise /api/firewall/alias_util/delete
        """
        data = {"address": address}
        res = await self._request('POST', f'/api/firewall/alias_util/delete/{alias_name}', data=data)
        if res.get('result') == 'removed' or res.get('status') == 'success':
             await self.reconfigure_alias()
        return res
    
    async def list_alias_content(self, alias_name: str) -> List[str]:
        """
        Liste le contenu actuel d'un alias via l'utilitaire atomique (table PF).
        
        Note: Utilise /api/firewall/alias_util/list
        """
        res = await self._request('GET', f'/api/firewall/alias_util/list/{alias_name}')
        if isinstance(res, dict) and 'rows' in res:
            return [row.get('ip') for row in res['rows'] if 'ip' in row]
        return []

    async def flush_alias(self, alias_name: str) -> Dict:
        """
        Vide l'alias via l'utilitaire atomique.
        
        Note: Utilise /api/firewall/alias_util/flush
        """
        res = await self._request('POST', f'/api/firewall/alias_util/flush/{alias_name}')
        if res.get('result') == 'flushed' or res.get('status') == 'success':
             await self.reconfigure_alias()
        return res

    async def reconfigure_alias(self) -> Dict:
        """Applique les changements d'alias."""
        return await self._request('POST', '/api/firewall/alias/reconfigure')
    
    async def find_alias_references(self, alias: str) -> Dict:
        """
        Trouve où un alias est utilisé dans la configuration.
        
        Args:
            alias: Nom de l'alias
            
        Returns:
            Liste des références
        """
        return await self._request('GET', '/api/firewall/alias_util/find_references', params={'alias': alias})
    
    # ========================================================================
    # NAT
    # ========================================================================
    
    async def add_nat_outbound(self, nat_data: Dict) -> Dict:
        """
        Crée une règle NAT sortant.
        
        Args:
            nat_data: Données de la règle NAT
            
        Returns:
            Réponse API
        """
        return await self._request('POST', '/api/firewall/source_nat/addRule', data=nat_data)
    
    async def delete_nat_outbound(self, uuid: str) -> Dict:
        """
        Supprime une règle NAT sortant.
        
        Args:
            uuid: UUID de la règle
            
        Returns:
            Réponse API
        """
        return await self._request('POST', f'/api/firewall/source_nat/delRule/{uuid}')
    
    async def add_nat_port_forward(self, nat_data: Dict) -> Dict:
        """
        Crée une redirection de port (NAT entrant).
        
        Args:
            nat_data: Données de la redirection
            
        Returns:
            Réponse API
        """
        # Note: OPNsense utilise le même endpoint pour port forward et NAT
        # La différence est dans les données envoyées
        return await self._request('POST', '/api/firewall/filter/addRule', data=nat_data)
    
    async def add_nat_one_to_one(self, nat_data: Dict) -> Dict:
        """
        Crée une règle NAT 1:1.
        
        Args:
            nat_data: Données du NAT 1:1
            
        Returns:
            Réponse API
        """
        return await self._request('POST', '/api/firewall/one_to_one/addRule', data=nat_data)
    
    async def delete_nat_one_to_one(self, uuid: str) -> Dict:
        """
        Supprime une règle NAT 1:1.
        
        Args:
            uuid: UUID de la règle
            
        Returns:
            Réponse API
        """
        return await self._request('POST', f'/api/firewall/one_to_one/delRule/{uuid}')
    
    # ========================================================================
    # Diagnostics & Logs
    # ========================================================================
    
    async def get_firewall_log(
        self,
        limit: int = 100,
        offset: int = 0,
        **filters
    ) -> Dict:
        """
        Récupère les logs du firewall.
        
        Args:
            limit: Nombre maximum d'entrées
            offset: Offset pour pagination
            **filters: Filtres optionnels (action, interface, protocol, etc.)
            
        Returns:
            Logs du firewall
        """
        params = {'limit': limit, 'offset': offset, **filters}
        return await self._request('GET', '/api/diagnostics/firewall/log', params=params)
    
    async def get_firewall_states(self, filter: Optional[str] = None) -> Dict:
        """
        Récupère les états actifs du firewall (connexions).
        
        Args:
            filter: Filtre de recherche (IP, port, etc.)
            
        Returns:
            États actifs
        """
        params = {'filter': filter} if filter else {}
        return await self._request('GET', '/api/diagnostics/firewall/pf_states', params=params)
    
    async def kill_firewall_states(self, filter: str) -> Dict:
        """
        Termine des états/connexions spécifiques.
        
        Args:
            filter: Filtre pour identifier les états (IP source/dest)
            
        Returns:
            Réponse API
        """
        return await self._request('POST', '/api/diagnostics/firewall/kill_states', data={'filter': filter})
    
    async def flush_firewall_states(self) -> Dict:
        """
        Vide tous les états du firewall (termine toutes les connexions).
        
        Returns:
            Réponse API
        """
        return await self._request('POST', '/api/diagnostics/firewall/flush_states')
    
    async def get_firewall_statistics(self) -> Dict:
        """
        Récupère les statistiques du firewall (paquets, bytes, etc.).
        
        Returns:
            Statistiques
        """
        return await self._request('GET', '/api/diagnostics/firewall/pf_statistics')
    
    async def get_rule_statistics(self) -> Dict:
        """
        Récupère les statistiques d'utilisation des règles.
        
        Returns:
            Statistiques par règle
        """
        return await self._request('GET', '/api/firewall/filter_util/rule_stats')
    
    # ========================================================================
    # Gestion de configuration
    # ========================================================================
    
    async def apply_firewall_changes(self, rollback_timeout: int = 0) -> Dict:
        """
        Applique les modifications du firewall.
        
        Args:
            rollback_timeout: Timeout de rollback automatique en secondes (0 = pas de rollback)
            
        Returns:
            Réponse API
        """
        data = {'rollback_timeout': rollback_timeout} if rollback_timeout > 0 else {}
        return await self._request('POST', '/api/firewall/filter/apply', data=data)
    
    async def cancel_firewall_rollback(self) -> Dict:
        """
        Annule un rollback automatique en attente (confirme les changements).
        
        Returns:
            Réponse API
        """
        return await self._request('POST', '/api/firewall/filter_base/cancel_rollback')
    
    async def revert_firewall_changes(self) -> Dict:
        """
        Annule les changements non appliqués et revient à la dernière configuration.
        
        Returns:
            Réponse API
        """
        try:
             return await self._request('POST', '/api/firewall/filter_base/revert', suppress_log_404=True)
        except OPNsenseAPIError as e:
             if '404' in str(e):
                 # Fallback for older/different OPNsense versions
                 logger.info("Fallback: trying /api/firewall/filter/revert")
                 return await self._request('POST', '/api/firewall/filter/revert')
             raise e
    
    async def create_firewall_savepoint(self, revision: Optional[str] = None) -> Dict:
        """
        Crée un point de sauvegarde de la configuration firewall.
        
        Args:
            revision: Nom/description du point de sauvegarde
            
        Returns:
            Réponse API
        """
        data = {'revision': revision} if revision else {}
        try:
            return await self._request('POST', '/api/firewall/filter_base/savepoint', data=data, suppress_log_404=True)
        except OPNsenseAPIError as e:
            if '404' in str(e):
                logger.info("Fallback: trying /api/firewall/filter/savepoint")
                return await self._request('POST', '/api/firewall/filter/savepoint', data=data)
            raise e
    
    async def get_interface_list(self) -> Dict:
        """
        Liste toutes les interfaces réseau disponibles via l'overview officiel.
        
        Note: Utilise /api/interfaces/overview/interfacesInfo
        """
        try:
            response = await self._request('GET', '/api/interfaces/overview/interfacesInfo', suppress_log_404=True)
            if isinstance(response, dict):
                # L'endpoint retourne un dictionnaire par device name (ex: "em0", "lo0")
                return {'interfaces': list(response.keys())}
        except Exception:
            pass

        # Fallback conservé pour compatibilité si l'overview échoue
        response = await self._request('GET', '/api/firewall/filter/get')
        
        interfaces = set()
        if 'filter' in response:
            rules_dict = response['filter'].get('rule', response['filter'].get('rules', {}).get('rule', {}))
            if isinstance(rules_dict, dict):
                for rule in rules_dict.values():
                    if isinstance(rule, dict) and 'interface' in rule:
                        iface = rule['interface']
                        if isinstance(iface, str):
                            interfaces.add(iface)
                        elif isinstance(iface, dict) and 'value' in iface:
                            interfaces.add(str(iface['value']))
        
        return {'interfaces': list(interfaces)} if interfaces else response
    
    # ========================================================================
    # Organisation
    # ========================================================================
    
    async def add_category(self, category_data: Dict) -> Dict:
        """
        Crée une catégorie pour organiser les règles.
        
        Args:
            category_data: Données de la catégorie (name, color, etc.)
            
        Returns:
            Réponse API
        """
        return await self._request('POST', '/api/firewall/category/addItem', data=category_data)
    
    async def delete_category(self, uuid: str) -> Dict:
        """
        Supprime une catégorie.
        
        Args:
            uuid: UUID de la catégorie
            
        Returns:
            Réponse API
        """
        return await self._request('POST', f'/api/firewall/category/delItem/{uuid}')
    
    async def list_categories(self) -> Dict:
        """
        Liste toutes les catégories disponibles.
        
        Returns:
            Liste des catégories
        """
        return await self._request('GET', '/api/firewall/category/get')
    
    async def list_available_categories(self) -> Dict:
        """Alias pour list_categories."""
        return await self.list_categories()
    
    async def update_bogons(self) -> Dict:
        """
        Met à jour les listes de réseaux bogons (réseaux réservés/invalides).
        
        Returns:
            Réponse API
        """
        return await self._request('POST', '/api/firewall/alias_util/update_bogons')
    
    # ========================================================================
    # Sauvegarde et Restauration
    # ========================================================================
    
    async def download_configuration(self) -> str:
        """
        Télécharge la configuration actuelle (config.xml).
        
        Returns:
            Contenu du fichier XML
        """
        # Note: Cet endpoint retourne du XML, pas du JSON
        url = urljoin(self.base_url, '/api/core/backup/download/this')
        try:
            response = await self.client.get('/api/core/backup/download/this')
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Backup download error: {e}")
            raise OPNsenseAPIError(f"Download failed: {str(e)}")

    async def list_restore_points(self) -> Dict:
        """
        Liste les points de restauration disponibles (historique).
        
        Returns:
            Liste des backups avec timestamp, description, etc.
        """
        # L'endpoint retourne la liste des backups pour le provider 'this' (local)
        return await self._request('GET', '/api/core/backup/backups/this')

    async def revert_to_restore_point(self, revision_id: str) -> Dict:
        """
        Restaure une configuration précédente.
        ATTENTION: Peut nécessiter un redémarrage ou recharger les services.
        
        Args:
            revision_id: ID de la révision (timestamp/id retourné par list_restore_points)
            
        Returns:
            Réponse API
        """
        # Le format attendu est souvent POST avec data={'id': revision_id}
        return await self._request('POST', f'/api/core/backup/revert/{revision_id}')

    # ========================================================================
    # GeoIP
    # ========================================================================
    
    async def list_geoip_countries(self) -> Dict:
        """
        Liste tous les pays disponibles pour les alias GeoIP.
        
        Returns:
            Liste des pays
        """
        return await self._request('GET', '/api/firewall/alias/list_countries')
    
    async def get_geoip_database(self) -> Dict:
        """
        Récupère les informations sur la base de données GeoIP.
        
        Returns:
            Informations GeoIP
        """
        return await self._request('GET', '/api/firewall/alias/get_geoip')

    # ========================================================================
    # Firmware & Updates
    # ========================================================================

    async def check_updates(self) -> Dict:
        """
        Vérifie la disponibilité des mises à jour du firmware.
        
        Returns:
            Réponse API avec statut des updates
        """
        # POST /api/core/firmware/check
        return await self._request('POST', '/api/core/firmware/check')

    async def get_upgrade_status(self) -> Dict:
        """
        Récupère le statut de la mise à jour en cours (ou terminée).
        
        Returns:
            Réponse API avec le statut
        """
        # GET /api/core/firmware/status
        return await self._request('GET', '/api/core/firmware/status')

    async def upgrade_firmware(self, upgrade_type: str = "pkg") -> Dict:
        """
        Déclenche la mise à jour du firmware.
        
        Args:
            upgrade_type: 'pkg' (paquets mineurs) ou 'all' (upgrade majeur/kernel)
            
        Returns:
            Réponse API confirmant le lancement
        """
        # POST /api/core/firmware/upgrade
        data = {'upgrade_type': upgrade_type}
        return await self._request('POST', '/api/core/firmware/upgrade', data=data)

    # ========================================================================
    # Unbound DNS
    # ========================================================================
    
    async def search_dns_overrides(self) -> Dict:
        """Récupère les host overrides Unbound."""
        return await self._request('POST', '/api/unbound/settings/searchHostOverride')

    async def add_dns_override(self, hostname: str, domain: str, ip: str, description: str = "") -> Dict:
        """Ajoute un host override."""
        data = {
            'host': {
                'enabled': '1',
                'hostname': hostname,
                'domain': domain,
                'rr': 'A',
                'server': ip,
                'description': description
            }
        }
        return await self._request('POST', '/api/unbound/settings/addHostOverride', data=data)

    async def delete_dns_override(self, uuid: str) -> Dict:
        """Supprime un host override."""
        return await self._request('POST', f'/api/unbound/settings/delHostOverride/{uuid}')

    async def reconfigure_unbound(self) -> Dict:
        """Applique les changements Unbound."""
        return await self._request('POST', '/api/unbound/service/reconfigure')

    async def manage_dns_blocklist(self, enabled: int = 1, force_download: bool = False) -> Dict:
        """Active/désactive la blocklist (AdGuard/Pi-hole like) d'Unbound."""
        data = {"unbound": {"dnsbl": {"enabled": str(enabled)}}}
        res = await self._request('POST', '/api/unbound/settings/set', data=data)
        
        if force_download:
            await self._request('POST', '/api/unbound/service/dnsbl')
            
        await self.reconfigure_unbound()
        return res

    async def search_dns_queries(self, search_phrase: str = "", limit: int = 100) -> Dict:
        """
        Recherche dans le log des requêtes DNS Unbound (Nécessite que le reporting soit actif).
        """
        params = {"current": 1, "rowCount": limit, "searchPhrase": search_phrase}
        return await self._request('POST', '/api/unbound/diagnostics/search', data=params)

    # ========================================================================
    # Diagnostics & Routing
    # ========================================================================

    async def ping_host(self, host: str, count: int = 3) -> Dict:
        """Ping un hôte depuis le firewall."""
        data = {"ping": {"count": str(count), "domain": host}}
        return await self._request('POST', '/api/diagnostics/ping/set', data=data)

    async def traceroute_host(self, host: str) -> Dict:
        """Trace la route vers un hôte."""
        data = {"traceroute": {"domain": host}}
        return await self._request('POST', '/api/diagnostics/traceroute/set', data=data)

    async def port_probe(self, host: str, port: int) -> Dict:
        """Test l'ouverture d'un port TCP."""
        data = {"portprobe": {"hostname": host, "port": str(port)}}
        return await self._request('POST', '/api/diagnostics/portprobe/set', data=data)

    async def get_static_routes(self) -> Dict:
        """Récupère les routes statiques configurées."""
        return await self._request('POST', '/api/routes/routes/searchroute')

    async def add_static_route(self, network: str, gateway: str, descr: str = "") -> Dict:
        """Ajoute une route statique."""
        data = {
            "route": {
                "network": network,
                "gateway": gateway,
                "descr": descr,
                "disabled": "0"
            }
        }
        res = await self._request('POST', '/api/routes/routes/addroute', data=data)
        await self._request('POST', '/api/routes/routes/reconfigure')
        return res

    async def delete_static_route(self, uuid: str) -> Dict:
        """Supprime une route statique via son UUID."""
        res = await self._request('POST', f'/api/routes/routes/delroute/{uuid}')
        await self._request('POST', '/api/routes/routes/reconfigure')
        return res

    # ========================================================================
    # DHCPv4
    # ========================================================================

    async def get_dhcp_leases(self) -> Dict:
        """Récupère les baux DHCP actifs."""
        return await self._request('GET', '/api/dhcpv4/leases/searchLease')

    async def get_static_mappings(self) -> Dict:
        """Récupère les réservations statiques."""
        return await self._request('GET', '/api/dhcpv4/settings/searchStaticMapping')

    async def add_static_mapping(self, mac: str, ip: str, hostname: str, description: str = "") -> Dict:
        """Ajoute une réservation statique."""
        data = {
            'staticmap': {
                'mac': mac,
                'ipaddr': ip,
                'hostname': hostname,
                'descr': description
            }
        }
        return await self._request('POST', '/api/dhcpv4/settings/addStaticMapping', data=data)

    # ========================================================================
    # Intrusion Detection (Suricata / IDS)
    # ========================================================================
    
    async def get_ids_status(self) -> Dict:
        """Récupère le statut du service IDS (Suricata)."""
        return await self._request('GET', '/api/ids/service/status')

    async def query_ids_alerts(self, limit: int = 100, offset: int = 0, search_phrase: str = "") -> Dict:
        """Récupère les alertes IDS."""
        params = {"current": (offset // limit) + 1, "rowCount": limit, "searchPhrase": search_phrase}
        return await self._request('POST', '/api/ids/service/queryAlerts', data=params)

    async def toggle_ids_rule(self, sid: str, enabled: int) -> Dict:
        """Active ou désactive une règle IDS par son SID."""
        data = {"sid": sid, "enabled": enabled}
        return await self._request('POST', '/api/ids/settings/toggleRule', data=data)

    async def reload_ids_rules(self) -> Dict:
        """Recharge les règles IDS (appliqué après un toggle_ids_rule)."""
        return await self._request('POST', '/api/ids/service/reloadRules')

    # ========================================================================
    # Service Monitoring & Self-Healing (Monit)
    # ========================================================================

    async def get_monit_status(self) -> Dict:
        """Récupère l'état de tous les services surveillés par Monit."""
        return await self._request('GET', '/api/monit/status/get')

    async def restart_monit_service(self, action: str, service: str) -> Dict:
        """
        Actionne un service géré par Monit (start, stop, restart, monitor, unmonitor).
        
        Args:
            action: Action à effectuer (ex: "restart")
            service: UUID ou nom du service à modifier
        """
        data = {"action": action, "uuid": service}
        return await self._request('POST', '/api/monit/status/setAction', data=data)

    # ========================================================================
    # Automation & Scheduling (Cron)
    # ========================================================================

    async def schedule_cron_job(self, command: str, parameters: str, description: str,
                                minutes: str = "*", hours: str = "*", days: str = "*",
                                months: str = "*", weekdays: str = "*") -> Dict:
        """Crée ou configure une tâche planifiée (Job Cron)."""
        data = {
            "job": {
                "enabled": "1",
                "minutes": minutes,
                "hours": hours,
                "days": days,
                "months": months,
                "weekdays": weekdays,
                "command": command,
                "parameters": parameters,
                "description": description
            }
        }
        return await self._request('POST', '/api/cron/settings/addJob', data=data)

    async def toggle_cron_job(self, uuid: str, enabled: int) -> Dict:
        """Active ou désactive une tâche Cron via UUID."""
        return await self._request('POST', f'/api/cron/settings/toggleJob/{uuid}/{enabled}')

    async def get_cron_jobs(self) -> Dict:
        """Récupère la liste des tâches Cron existantes."""
        return await self._request('GET', '/api/cron/settings/searchJobs')

    # ========================================================================
    # IDS complémentaire (Suricata) — Lot 1
    # ========================================================================

    async def list_ids_rulesets(self) -> Dict:
        """Liste les rulesets IDS disponibles (activés et désactivés)."""
        return await self._request('GET', '/api/ids/settings/listRulesets')

    async def toggle_ids_ruleset(self, filename: str, enabled: int) -> Dict:
        """Active (1) ou désactive (0) un ruleset IDS par nom de fichier."""
        return await self._request('POST', f'/api/ids/settings/toggleRuleset/{filename}/{enabled}')

    async def update_ids_rules(self) -> Dict:
        """Télécharge et met à jour les règles IDS depuis les sources upstream."""
        return await self._request('POST', '/api/ids/service/updateRules')

    async def start_ids(self) -> Dict:
        """Démarre le service IDS (Suricata)."""
        return await self._request('POST', '/api/ids/service/start')

    async def stop_ids(self) -> Dict:
        """Arrête le service IDS (Suricata)."""
        return await self._request('POST', '/api/ids/service/stop')

    async def restart_ids(self) -> Dict:
        """Redémarre le service IDS (Suricata)."""
        return await self._request('POST', '/api/ids/service/restart')

    # ========================================================================
    # Traffic Shaping (QoS dummynet) — Lot 2
    # ========================================================================

    async def get_traffic_statistics(self) -> Dict:
        """Retourne les statistiques de trafic en temps réel (débit par pipe/queue)."""
        return await self._request('GET', '/api/trafficshaper/service/statistics')

    async def list_traffic_pipes(self) -> Dict:
        """Liste tous les pipes de traffic shaping."""
        return await self._request('GET', '/api/trafficshaper/settings/getPipe')

    async def add_traffic_pipe(self, description: str, bandwidth: int,
                               bandwidth_metric: str = "Mbit") -> Dict:
        """Crée un pipe de traffic shaping (limitation de bande passante)."""
        data = {"pipe": {"description": description, "bandwidth": str(bandwidth),
                         "bandwidthMetric": bandwidth_metric, "enabled": "1"}}
        return await self._request('POST', '/api/trafficshaper/settings/addPipe', data=data)

    async def del_traffic_pipe(self, uuid: str) -> Dict:
        """Supprime un pipe de traffic shaping."""
        return await self._request('POST', f'/api/trafficshaper/settings/delPipe/{uuid}')

    async def list_traffic_queues(self) -> Dict:
        """Liste toutes les queues de traffic shaping."""
        return await self._request('GET', '/api/trafficshaper/settings/getQueue')

    async def add_traffic_queue(self, description: str, pipe: str,
                                weight: int = 100) -> Dict:
        """Crée une queue attachée à un pipe (priorisation interne)."""
        data = {"queue": {"description": description, "pipe": pipe,
                          "weight": str(weight), "enabled": "1"}}
        return await self._request('POST', '/api/trafficshaper/settings/addQueue', data=data)

    async def del_traffic_queue(self, uuid: str) -> Dict:
        """Supprime une queue de traffic shaping."""
        return await self._request('POST', f'/api/trafficshaper/settings/delQueue/{uuid}')

    async def list_traffic_rules(self) -> Dict:
        """Liste les règles de traffic shaping (classification du trafic)."""
        return await self._request('GET', '/api/trafficshaper/settings/getRule')

    async def add_traffic_rule(self, description: str, sequence: int,
                               target: str, source: str = "any",
                               destination: str = "any") -> Dict:
        """Crée une règle de classification du trafic vers un pipe ou une queue."""
        data = {"rule": {"description": description, "sequence": str(sequence),
                         "source": source, "destination": destination,
                         "target": target, "enabled": "1"}}
        return await self._request('POST', '/api/trafficshaper/settings/addRule', data=data)

    async def del_traffic_rule(self, uuid: str) -> Dict:
        """Supprime une règle de traffic shaping."""
        return await self._request('POST', f'/api/trafficshaper/settings/delRule/{uuid}')

    async def apply_traffic_changes(self) -> Dict:
        """Applique les changements de traffic shaping (reconfigure dummynet)."""
        return await self._request('POST', '/api/trafficshaper/service/reconfigure')

    # ========================================================================
    # ACME / Certificats Let's Encrypt — Lot 3
    # ========================================================================

    async def get_acme_status(self) -> Dict:
        """Retourne l'état du service ACME client (Let's Encrypt)."""
        return await self._request('GET', '/api/acmeclient/service/status')

    async def list_acme_certificates(self) -> Dict:
        """Liste tous les certificats ACME gérés."""
        return await self._request('GET', '/api/acmeclient/certificates/get')

    async def sign_acme_certificate(self, uuid: str) -> Dict:
        """Déclenche la demande/renouvellement d'un certificat via ACME (Let's Encrypt)."""
        return await self._request('POST', f'/api/acmeclient/certificates/sign/{uuid}')

    async def update_acme_certificate(self, uuid: str) -> Dict:
        """Force la mise à jour d'un certificat ACME existant."""
        return await self._request('POST', f'/api/acmeclient/certificates/update/{uuid}')

    async def revoke_acme_certificate(self, uuid: str) -> Dict:
        """Révoque un certificat ACME."""
        return await self._request('POST', f'/api/acmeclient/certificates/revoke/{uuid}')

    async def list_acme_accounts(self) -> Dict:
        """Liste les comptes ACME (Let's Encrypt) configurés."""
        return await self._request('GET', '/api/acmeclient/accounts/get')

    # ========================================================================
    # IPsec — Lot 4
    # ========================================================================

    async def get_ipsec_status(self) -> Dict:
        """Retourne l'état du service IPsec (strongSwan)."""
        return await self._request('GET', '/api/ipsec/service/status')

    async def list_ipsec_connections(self) -> Dict:
        """Liste toutes les connexions IPsec configurées."""
        return await self._request('GET', '/api/ipsec/connections/get')

    async def toggle_ipsec_connection(self, uuid: str, enabled: int) -> Dict:
        """Active (1) ou désactive (0) une connexion IPsec."""
        return await self._request('POST', f'/api/ipsec/connections/toggleConnection/{uuid}/{enabled}')

    async def list_ipsec_sessions(self) -> Dict:
        """Liste les sessions IPsec actives (phase 1)."""
        return await self._request('GET', '/api/ipsec/sessions/searchPhase1')

    async def connect_ipsec_session(self, session_id: str) -> Dict:
        """Établit une session IPsec identifiée par son ID."""
        return await self._request('POST', f'/api/ipsec/sessions/connect/{session_id}')

    async def disconnect_ipsec_session(self, session_id: str) -> Dict:
        """Déconnecte une session IPsec active."""
        return await self._request('POST', f'/api/ipsec/sessions/disconnect/{session_id}')

    async def apply_ipsec_changes(self) -> Dict:
        """Applique les modifications de configuration IPsec."""
        return await self._request('POST', '/api/ipsec/service/reconfigure')

    # ========================================================================
    # OpenVPN — Lot 4
    # ========================================================================

    async def list_openvpn_instances(self) -> Dict:
        """Liste toutes les instances OpenVPN (serveurs et clients) configurées."""
        return await self._request('GET', '/api/openvpn/instances/get')

    async def toggle_openvpn_instance(self, uuid: str, enabled: int) -> Dict:
        """Active (1) ou désactive (0) une instance OpenVPN."""
        return await self._request('POST', f'/api/openvpn/instances/toggle/{uuid}/{enabled}')

    async def list_openvpn_sessions(self) -> Dict:
        """Liste les sessions OpenVPN actives (clients connectés)."""
        return await self._request('GET', '/api/openvpn/service/searchSessions')

    async def kill_openvpn_session(self, common_name: str, address: str) -> Dict:
        """Déconnecte de force un client OpenVPN par CN et adresse."""
        data = {"common_name": common_name, "address": address}
        return await self._request('POST', '/api/openvpn/service/killSession', data=data)

    async def apply_openvpn_changes(self) -> Dict:
        """Applique les modifications de configuration OpenVPN."""
        return await self._request('POST', '/api/openvpn/service/reconfigure')
