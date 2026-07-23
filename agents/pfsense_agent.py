# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Agent-outil pour firewall pfSense.

Cet agent hérite d'OPNsenseAgent car pfSense et OPNsense partagent
environ 80-90% de leur API (OPNsense est un fork de pfSense).

Les 40 fonctions sont héritées automatiquement, seules les différences
spécifiques à pfSense sont surchargées.
"""

import logging
from typing import Dict, List, Literal, Optional

from .opnsense_agent import OPNsenseAgent

logger = logging.getLogger(__name__)


class PfSenseAgent(OPNsenseAgent):
    """
    Agent-outil pour firewall pfSense.
    
    Hérite d'OPNsenseAgent car les deux firewalls partagent 80-90% de leur API.
    
    Fonctions supportées (40 au total, héritées d'OPNsense):
    - Règles de filtrage (6): create, delete, update, toggle, move, get
    - Alias (10): create, delete, update, get, import, flush, add_to, delete_from, list_content, find_references
    - NAT (5): outbound, port_forward, one_to_one, delete_outbound, delete_one_to_one
    - Diagnostics (6): logs, states, kill_states, flush_states, statistics, rule_stats
    - Gestion (5): apply, cancel_rollback, revert, savepoint, get_interfaces
    - Organisation (4): create_category, delete_category, list_categories, update_bogons
    - GeoIP (2): list_countries, get_database
    - Utilitaires (2): block_ip, unblock_ip (legacy)
    
    Différences avec OPNsense :
    - Client API pfSense (gère les différences d'endpoints)
    - Quelques méthodes adaptées pour pfSense
    - Support des packages pfSense
    """

    def __init__(self, model_path: str, api_config: Optional[Dict] = None):
        """
        Initialise l'agent pfSense.
        
        Args:
            model_path: Chemin vers le modèle LoRA
            api_config: Configuration API pfSense
        """
        # Initialiser la classe parente (OPNsense)
        # On passe tool_name="pfsense" pour identifier l'agent
        super().__init__(model_path, api_config)
        
        # Changer le nom de l'outil
        self.tool_name = "pfsense"
        
        # Remplacer le client API par un client pfSense
        self._api_client = None
        if api_config and all(k in api_config for k in ['base_url', 'api_key', 'api_secret']):
            from clients.pfsense_api_client import PfSenseAPIClient
            
            self._api_client = PfSenseAPIClient(
                base_url=api_config['base_url'],
                api_key=api_config['api_key'],
                api_secret=api_config['api_secret'],
                api_version=api_config.get('api_version', 'v1'),
                verify_ssl=api_config.get('verify_ssl', True),
                timeout=api_config.get('timeout', 30)
            )
            logger.info("✓ pfSense API client initialized")
        else:
            logger.warning("⚠️  Mode simulation : pas de configuration API fournie")

    # ========================================================================
    # Méthodes héritées d'OPNsense
    # ========================================================================
    
    # Toutes les 40 méthodes sont héritées automatiquement !
    # Pas besoin de les réécrire, elles fonctionnent directement.
    
    # Le client API pfSense gère les différences (noms de champs, endpoints)
    # donc les méthodes héritées fonctionnent sans modification.

    # ========================================================================
    # Surcharges spécifiques pfSense (si nécessaire)
    # ========================================================================

    async def _create_filter_rule(
        self,
        description: str,
        interface: Literal["wan", "lan", "opt1", "opt2"],
        protocol: Literal["any", "tcp", "udp", "icmp"] = "any",
        action: Literal["block", "pass"] = "block",
        **kwargs
    ) -> Dict:
        """Crée une règle de filtrage firewall pfSense.

        :param description: Description lisible de la règle.
        :param interface: Interface réseau cible. 'wan' pour le trafic Internet entrant,
            'lan' pour le réseau local, 'opt1'/'opt2' pour les interfaces optionnelles.
            Ne pas créer d'alias pour une interface — utiliser directement son nom.
        :param protocol: Protocole concerné : 'any' (tous), 'tcp', 'udp' ou 'icmp'.
        :param action: Action à appliquer : 'block' pour bloquer, 'pass' pour autoriser.
            NE PAS utiliser 'allow', 'deny' ou 'drop'.
        """
        logger.info(f"[pfSense] Creating rule: {description}")
        
        # Appeler la méthode parente
        # Le client API pfSense gère les adaptations automatiquement
        return await super()._create_filter_rule(
            description, interface, protocol, action, **kwargs
        )

    async def _create_alias(
        self,
        name: str,
        type: Literal["host", "network", "port", "url", "urltable", "geoip"],
        content: List[str],
        description: str = ""
    ) -> Dict:
        """Crée un alias pfSense (groupe nommé d'IPs, réseaux, ports ou URLs).

        :param name: Nom de l'alias (sans espaces, ex: "blocked_ips", "trusted_nets").
        :param type: Type de contenu : 'host' (IPs), 'network' (CIDRs), 'port' (ports/plages),
            'url' (URL résolue à l'import), 'urltable' (URL rechargée périodiquement),
            'geoip' (pays par code ISO). Ne pas créer d'alias pour une interface réseau.
        :param content: Liste des valeurs (ex: ["192.168.1.0/24", "10.0.0.1"]).
        :param description: Description optionnelle de l'alias.
        """
        logger.info(f"[pfSense] Creating alias: {name} (type: {type})")
        
        # Appeler la méthode parente
        return await super()._create_alias(name, type, content, description)

    # ========================================================================
    # Méthodes spécifiques pfSense (non présentes dans OPNsense)
    # ========================================================================

    async def _get_system_info(self) -> Dict:
        """
        Récupère les informations système de pfSense.
        
        MÉTHODE SPÉCIFIQUE pfSense.
        """
        logger.info(f"[pfSense] Retrieving system info")

        if self._api_client:
            try:
                return await self._api_client.get_system_info()
            except Exception as e:
                logger.error(f"Error retrieving system info: {e}")
                return {"status": "error", "message": str(e)}
        
        return {
            "platform": "pfSense",
            "version": "unknown",
            "mode": "simulation"
        }

    async def _list_packages(self) -> Dict:
        """
        Liste les packages installés sur pfSense.
        
        MÉTHODE SPÉCIFIQUE pfSense.
        """
        logger.info(f"[pfSense] Liste des packages")
        
        if self._api_client:
            try:
                return await self._api_client.get_packages()
            except Exception as e:
                logger.error(f"Erreur liste packages: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"packages": [], "mode": "simulation"}

    async def _install_package(self, package_name: str) -> Dict:
        """
        Installe un package pfSense.
        
        MÉTHODE SPÉCIFIQUE pfSense.
        
        Args:
            package_name: Nom du package à installer
        """
        logger.info(f"[pfSense] Installation package: {package_name}")
        
        if self._api_client:
            try:
                response = await self._api_client.install_package(package_name)
                logger.info(f"✓ Package {package_name} installed")
                return response
            except Exception as e:
                logger.error(f"Erreur installation package: {e}")
                return {"status": "error", "message": str(e)}
        
        return {
            "status": "installed",
            "package": package_name,
            "mode": "simulation"
        }

    def _register_functions(self) -> Dict[str, callable]:
        """
        Enregistre toutes les fonctions pfSense.
        
        Hérite des 40 fonctions OPNsense + ajoute les fonctions spécifiques pfSense.
        """
        # Récupérer les fonctions héritées d'OPNsense
        functions = super()._register_functions()
        
        # Ajouter les fonctions spécifiques pfSense
        functions.update({
            "get_system_info": self._get_system_info,
            "list_packages": self._list_packages,
            "install_package": self._install_package,
        })
        
        logger.info(f"Agent pfSense: {len(functions)} functions registered (40 OPNsense + 3 pfSense)")
        
        return functions

    def get_tool_spec(self) -> Dict:
        """
        Retourne la spécification de l'outil pour le LoRA.
        
        Surcharge pour indiquer qu'il s'agit de pfSense.
        """
        spec = super().get_tool_spec()
        spec['tool_name'] = 'pfsense'
        spec['description'] = 'Agent pfSense firewall avec 43 fonctions (40 héritées OPNsense + 3 spécifiques)'
        return spec


# ============================================================================
# Fonctions utilitaires
# ============================================================================

def create_pfsense_agent(model_path: str, api_config: Optional[Dict] = None) -> PfSenseAgent:
    """
    Crée un agent pfSense.
    
    Args:
        model_path: Chemin vers le modèle LoRA
        api_config: Configuration API pfSense
    
    Returns:
        Instance de PfSenseAgent
    
    Example:
        >>> from config.pfsense_config import PFSENSE_CONFIG
        >>> agent = create_pfsense_agent('models/pfsense_lora/adapter', PFSENSE_CONFIG)
        >>> result = await agent.execute("Lister les règles de filtrage")
    """
    return PfSenseAgent(model_path=model_path, api_config=api_config)
