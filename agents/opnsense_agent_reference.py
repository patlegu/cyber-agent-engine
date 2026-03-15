"""
Agent-outil pour firewall OPNsense - VERSION DE RÉFÉRENCE AVEC API RÉELLE.

ATTENTION : Ce fichier est une CORRECTION/RÉFÉRENCE pour l'implémentation des appels API réels.
Il contient les 40 fonctions avec les vrais appels à OPNsenseAPIClient.

Utilisez ce fichier comme référence pour comparer avec votre propre implémentation.

Fichier original (simulation) : factory/agents/opnsense_agent.py
Fichier de référence (API réelle) : factory/agents/opnsense_agent_reference.py (ce fichier)
"""

import logging
from typing import Dict, List, Optional

from .base import ToolAgent

logger = logging.getLogger(__name__)


class OPNsenseAgentReference(ToolAgent):
    """
    Agent-outil pour firewall OPNsense - VERSION DE RÉFÉRENCE avec API réelle.
    
    Cette version implémente les 40 fonctions avec de vrais appels API.
    Utilisez-la comme référence pour votre propre implémentation.

    Fonctions supportées (40 au total):
    - Règles de filtrage (6): create, delete, update, toggle, move, get
    - Alias (10): create, delete, update, get, import, flush, add_to, delete_from, list_content, find_references
    - NAT (5): outbound, port_forward, one_to_one, delete_outbound, delete_one_to_one
    - Diagnostics (6): logs, states, kill_states, flush_states, statistics, rule_stats
    - Gestion (5): apply, cancel_rollback, revert, savepoint, get_interfaces
    - Organisation (4): create_category, delete_category, list_categories, update_bogons
    - GeoIP (2): list_countries, get_database
    - Utilitaires (2): block_ip, unblock_ip (legacy)
    """

    def __init__(self, model_path: str, api_config: Optional[Dict] = None):
        super().__init__(
            tool_name="opnsense",
            model_path=model_path,
            api_config=api_config
        )
        
        # Initialiser le client API si la configuration est fournie
        self._api_client = None
        if api_config and all(k in api_config for k in ['base_url', 'api_key', 'api_secret']):
            from factory.clients import OPNsenseAPIClient
            self._api_client = OPNsenseAPIClient(
                base_url=api_config['base_url'],
                api_key=api_config['api_key'],
                api_secret=api_config['api_secret'],
                verify_ssl=api_config.get('verify_ssl', True),
                timeout=api_config.get('timeout', 30)
            )
            logger.info("✓ Client API OPNsense initialisé (VERSION RÉFÉRENCE)")
        else:
            logger.warning("⚠️  Mode simulation : pas de configuration API fournie")

    def _register_functions(self) -> Dict[str, callable]:
        """Enregistre toutes les fonctions OPNsense."""
        return {
            # Legacy (compatibilité)
            "block_ip": self._block_ip,
            "unblock_ip": self._unblock_ip,
            
            # Règles de filtrage
            "create_filter_rule": self._create_filter_rule,
            "delete_filter_rule": self._delete_filter_rule,
            "update_filter_rule": self._update_filter_rule,
            "toggle_filter_rule": self._toggle_filter_rule,
            "move_filter_rule": self._move_filter_rule,
            "get_filter_rule": self._get_filter_rule,
            
            # Alias
            "create_alias": self._create_alias,
            "delete_alias": self._delete_alias,
            "update_alias": self._update_alias,
            "get_alias": self._get_alias,
            "import_alias": self._import_alias,
            "flush_alias": self._flush_alias,
            "add_to_alias": self._add_to_alias,
            "delete_from_alias": self._delete_from_alias,
            "list_alias_content": self._list_alias_content,
            "find_alias_references": self._find_alias_references,
            
            # NAT
            "create_nat_outbound": self._create_nat_outbound,
            "delete_nat_outbound": self._delete_nat_outbound,
            "create_nat_port_forward": self._create_nat_port_forward,
            "create_nat_one_to_one": self._create_nat_one_to_one,
            "delete_nat_one_to_one": self._delete_nat_one_to_one,
            
            # Diagnostics & Logs
            "get_firewall_log": self._get_firewall_log,
            "get_firewall_states": self._get_firewall_states,
            "kill_firewall_states": self._kill_firewall_states,
            "flush_firewall_states": self._flush_firewall_states,
            "get_firewall_statistics": self._get_firewall_statistics,
            "get_rule_statistics": self._get_rule_statistics,
            
            # Gestion de configuration
            "apply_firewall_changes": self._apply_firewall_changes,
            "cancel_firewall_rollback": self._cancel_firewall_rollback,
            "revert_firewall_changes": self._revert_firewall_changes,
            "create_firewall_savepoint": self._create_firewall_savepoint,
            "get_interface_list": self._get_interface_list,
            
            # Organisation
            "create_category": self._create_category,
            "delete_category": self._delete_category,
            "list_available_categories": self._list_available_categories,
            "update_bogons": self._update_bogons,
            
            # GeoIP
            "list_geoip_countries": self._list_geoip_countries,
            "get_geoip_database": self._get_geoip_database,
        }

    # ========================================================================
    # Legacy Functions (compatibilité)
    # ========================================================================

    async def _block_ip(self, ip: str, description: str = "Blocked by agent") -> Dict:
        """
        Bloque une adresse IP (legacy - utilise add_to_alias en interne).
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Utilise add_to_alias pour ajouter l'IP à un alias de blocage
        - Applique automatiquement les changements
        """
        logger.info(f"[OPNsense] Blocage IP: {ip}")
        
        if self._api_client:
            try:
                # Utiliser l'alias "BlockedIPs" (doit exister)
                result = await self._add_to_alias("BlockedIPs", ip)
                
                return {
                    "status": "blocked",
                    "ip": ip,
                    "alias": "BlockedIPs",
                    "result": result
                }
            except Exception as e:
                logger.error(f"Erreur blocage IP: {e}")
                return {"status": "error", "message": str(e)}
        
        # Fallback simulation
        return {
            "status": "blocked",
            "ip": ip,
            "alias": "BlockedIPs",
            "mode": "simulation"
        }

    async def _unblock_ip(self, ip: str) -> Dict:
        """
        Débloque une adresse IP (legacy).
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Utilise delete_from_alias pour retirer l'IP
        - Applique automatiquement les changements
        """
        logger.info(f"[OPNsense] Déblocage IP: {ip}")
        
        if self._api_client:
            try:
                result = await self._delete_from_alias("BlockedIPs", ip)
                
                return {
                    "status": "unblocked",
                    "ip": ip,
                    "result": result
                }
            except Exception as e:
                logger.error(f"Erreur déblocage IP: {e}")
                return {"status": "error", "message": str(e)}
        
        # Fallback simulation
        return {
            "status": "unblocked",
            "ip": ip,
            "mode": "simulation"
        }

    # ========================================================================
    # Règles de filtrage
    # ========================================================================

    async def _create_filter_rule(
        self,
        description: str,
        interface: str,
        protocol: str = "any",
        action: str = "block",
        **kwargs
    ) -> Dict:
        """
        Crée une règle de filtrage firewall.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Prépare les données au format OPNsense
        - Appelle add_filter_rule du client API
        - Applique automatiquement les changements si succès
        """
        logger.info(f"[OPNsense] Création règle: {description}")
        
        if self._api_client:
            try:
                # Préparer les données de la règle
                rule_data = {
                    "rule": {
                        "description": description,
                        "interface": interface,
                        "protocol": protocol,
                        "type": action,  # OPNsense utilise "type" pour l'action
                        "enabled": "1",
                        **{k: v for k, v in kwargs.items() if v is not None}
                    }
                }
                
                # Appeler l'API
                response = self._api_client.add_filter_rule(rule_data)
                
                # Appliquer les changements si succès
                if response.get('result') == 'saved':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Règle '{description}' créée et appliquée")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur création règle: {e}")
                return {"status": "error", "message": str(e)}
        
        # Fallback simulation
        return {
            "status": "created",
            "uuid": f"rule-{hash(description) % 10000}",
            "description": description,
            "mode": "simulation"
        }

    async def _delete_filter_rule(self, uuid: str) -> Dict:
        """
        Supprime une règle de filtrage.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle delete_filter_rule du client API
        - Applique automatiquement les changements
        """
        logger.info(f"[OPNsense] Suppression règle: {uuid}")
        
        if self._api_client:
            try:
                response = self._api_client.delete_filter_rule(uuid)
                
                if response.get('result') == 'deleted':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Règle {uuid} supprimée et appliquée")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur suppression règle: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "deleted", "uuid": uuid, "mode": "simulation"}

    async def _update_filter_rule(self, uuid: str, **kwargs) -> Dict:
        """
        Modifie une règle de filtrage existante.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Prépare les modifications
        - Appelle update_filter_rule du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Modification règle: {uuid}")
        
        if self._api_client:
            try:
                rule_data = {
                    "rule": {k: v for k, v in kwargs.items() if v is not None}
                }
                
                response = self._api_client.update_filter_rule(uuid, rule_data)
                
                if response.get('result') == 'saved':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Règle {uuid} modifiée et appliquée")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur modification règle: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "updated", "uuid": uuid, "mode": "simulation"}

    async def _toggle_filter_rule(self, uuid: str, enabled: bool) -> Dict:
        """
        Active ou désactive une règle.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle toggle_filter_rule du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Toggle règle {uuid}: {'enabled' if enabled else 'disabled'}")
        
        if self._api_client:
            try:
                response = self._api_client.toggle_filter_rule(uuid, enabled)
                
                if response.get('result') == 'saved':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Règle {uuid} {'activée' if enabled else 'désactivée'}")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur toggle règle: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "toggled", "uuid": uuid, "enabled": enabled, "mode": "simulation"}

    async def _move_filter_rule(self, uuid: str, before_uuid: str) -> Dict:
        """
        Déplace une règle avant une autre.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle move_filter_rule du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Déplacement règle {uuid} avant {before_uuid}")
        
        if self._api_client:
            try:
                response = self._api_client.move_filter_rule(uuid, before_uuid)
                
                if response.get('result') == 'saved':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Règle {uuid} déplacée")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur déplacement règle: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "moved", "uuid": uuid, "mode": "simulation"}

    async def _get_filter_rule(self, uuid: Optional[str] = None) -> Dict:
        """
        Récupère une ou toutes les règles de filtrage.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle get_filter_rule du client API
        - Pas besoin d'apply (lecture seule)
        """
        logger.info(f"[OPNsense] Consultation règles{f': {uuid}' if uuid else ''}")
        
        if self._api_client:
            try:
                return self._api_client.get_filter_rule(uuid)
            except Exception as e:
                logger.error(f"Erreur consultation règles: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"total": 42, "rules": [], "mode": "simulation"}

    # ========================================================================
    # Alias
    # ========================================================================

    async def _create_alias(
        self,
        name: str,
        type: str,
        content: List[str],
        description: str = ""
    ) -> Dict:
        """
        Crée un alias (host, network, port, url, geoip).
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Convertit la liste en chaîne avec \n (format OPNsense)
        - Appelle add_alias du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Création alias: {name} (type: {type})")
        
        if self._api_client:
            try:
                alias_data = {
                    "alias": {
                        "name": name,
                        "type": type,
                        "content": "\n".join(content),  # OPNsense attend une chaîne
                        "description": description,
                        "enabled": "1"
                    }
                }
                
                response = self._api_client.add_alias(alias_data)
                
                if response.get('result') == 'saved':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Alias '{name}' créé et appliqué")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur création alias: {e}")
                return {"status": "error", "message": str(e)}
        
        return {
            "status": "created",
            "uuid": f"alias-{hash(name) % 10000}",
            "name": name,
            "mode": "simulation"
        }

    async def _delete_alias(self, uuid: str) -> Dict:
        """
        Supprime un alias.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle delete_alias du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Suppression alias: {uuid}")
        
        if self._api_client:
            try:
                response = self._api_client.delete_alias(uuid)
                
                if response.get('result') == 'deleted':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Alias {uuid} supprimé")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur suppression alias: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "deleted", "uuid": uuid, "mode": "simulation"}

    async def _update_alias(self, uuid: str, **kwargs) -> Dict:
        """
        Modifie un alias existant.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Si 'content' est une liste, la convertir en chaîne
        - Appelle update_alias du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Modification alias: {uuid}")
        
        if self._api_client:
            try:
                # Convertir content si c'est une liste
                if 'content' in kwargs and isinstance(kwargs['content'], list):
                    kwargs['content'] = "\n".join(kwargs['content'])
                
                alias_data = {
                    "alias": {k: v for k, v in kwargs.items() if v is not None}
                }
                
                response = self._api_client.update_alias(uuid, alias_data)
                
                if response.get('result') == 'saved':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Alias {uuid} modifié")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur modification alias: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "updated", "uuid": uuid, "mode": "simulation"}

    async def _get_alias(self, uuid: Optional[str] = None) -> Dict:
        """
        Récupère un ou tous les alias.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle get_alias du client API
        - Pas besoin d'apply (lecture seule)
        """
        logger.info(f"[OPNsense] Consultation alias{f': {uuid}' if uuid else ''}")
        
        if self._api_client:
            try:
                return self._api_client.get_alias(uuid)
            except Exception as e:
                logger.error(f"Erreur consultation alias: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"total": 15, "aliases": [], "mode": "simulation"}

    async def _import_alias(self, uuid: str, content: str) -> Dict:
        """
        Importe des entrées dans un alias depuis un fichier/URL.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle import_alias du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Import dans alias: {uuid}")
        
        if self._api_client:
            try:
                response = self._api_client.import_alias(uuid, content)
                
                if response.get('result') == 'saved':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Import dans alias {uuid} effectué")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur import alias: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "imported", "uuid": uuid, "mode": "simulation"}

    async def _flush_alias(self, alias: str) -> Dict:
        """
        Vide toutes les entrées d'un alias.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle flush_alias du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Flush alias: {alias}")
        
        if self._api_client:
            try:
                response = self._api_client.flush_alias(alias)
                
                if response.get('result') == 'flushed':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Alias {alias} vidé")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur flush alias: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "flushed", "alias": alias, "mode": "simulation"}

    async def _add_to_alias(self, alias: str, address: str) -> Dict:
        """
        Ajoute une entrée à un alias.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle add_to_alias du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Ajout {address} à alias {alias}")
        
        if self._api_client:
            try:
                response = self._api_client.add_to_alias(alias, address)
                
                if response.get('result') == 'added':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ {address} ajouté à {alias}")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur ajout à alias: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "added", "alias": alias, "address": address, "mode": "simulation"}

    async def _delete_from_alias(self, alias: str, address: str) -> Dict:
        """
        Retire une entrée d'un alias.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle delete_from_alias du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Retrait {address} de alias {alias}")
        
        if self._api_client:
            try:
                response = self._api_client.delete_from_alias(alias, address)
                
                if response.get('result') == 'removed':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ {address} retiré de {alias}")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur retrait alias: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "removed", "alias": alias, "address": address, "mode": "simulation"}

    async def _list_alias_content(self, alias: str) -> Dict:
        """
        Liste le contenu actuel d'un alias (table PF).
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle list_alias_content du client API
        - Pas besoin d'apply (lecture seule)
        """
        logger.info(f"[OPNsense] Liste contenu alias: {alias}")
        
        if self._api_client:
            try:
                return self._api_client.list_alias_content(alias)
            except Exception as e:
                logger.error(f"Erreur liste contenu alias: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"alias": alias, "content": [], "mode": "simulation"}

    async def _find_alias_references(self, alias: str) -> Dict:
        """
        Trouve où un alias est utilisé.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle find_alias_references du client API
        - Pas besoin d'apply (lecture seule)
        """
        logger.info(f"[OPNsense] Recherche références alias: {alias}")
        
        if self._api_client:
            try:
                return self._api_client.find_alias_references(alias)
            except Exception as e:
                logger.error(f"Erreur recherche références: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"alias": alias, "references": [], "mode": "simulation"}

    # ========================================================================
    # NAT
    # ========================================================================

    async def _create_nat_outbound(
        self,
        interface: str,
        source: str,
        **kwargs
    ) -> Dict:
        """
        Crée une règle NAT sortant (masquerading).
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Prépare les données NAT
        - Appelle create_nat_outbound du client API
        - Applique les changements
        """
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
                
                response = self._api_client.create_nat_outbound(nat_data)
                
                if response.get('result') == 'saved':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ NAT sortant créé")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur création NAT sortant: {e}")
                return {"status": "error", "message": str(e)}
        
        return {
            "status": "created",
            "uuid": f"nat-out-{hash(source) % 10000}",
            "mode": "simulation"
        }

    async def _delete_nat_outbound(self, uuid: str) -> Dict:
        """
        Supprime une règle NAT sortant.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle delete_nat_outbound du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Suppression NAT sortant: {uuid}")
        
        if self._api_client:
            try:
                response = self._api_client.delete_nat_outbound(uuid)
                
                if response.get('result') == 'deleted':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ NAT sortant {uuid} supprimé")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur suppression NAT sortant: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "deleted", "uuid": uuid, "mode": "simulation"}

    async def _create_nat_port_forward(
        self,
        interface: str,
        protocol: str,
        destination_port: str,
        redirect_target_ip: str,
        redirect_target_port: str,
        **kwargs
    ) -> Dict:
        """
        Crée une redirection de port.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Prépare les données de port forwarding
        - Appelle create_nat_port_forward du client API
        - Applique les changements
        """
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
                
                response = self._api_client.create_nat_port_forward(pf_data)
                
                if response.get('result') == 'saved':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Port forward créé")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur création port forward: {e}")
                return {"status": "error", "message": str(e)}
        
        return {
            "status": "created",
            "uuid": f"pf-{hash(destination_port) % 10000}",
            "mode": "simulation"
        }

    async def _create_nat_one_to_one(
        self,
        interface: str,
        external_ip: str,
        internal_ip: str,
        **kwargs
    ) -> Dict:
        """
        Crée un NAT 1:1 (bimap).
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Prépare les données NAT 1:1
        - Appelle create_nat_one_to_one du client API
        - Applique les changements
        """
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
                
                response = self._api_client.create_nat_one_to_one(nat_data)
                
                if response.get('result') == 'saved':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ NAT 1:1 créé")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur création NAT 1:1: {e}")
                return {"status": "error", "message": str(e)}
        
        return {
            "status": "created",
            "uuid": f"nat1to1-{hash(external_ip) % 10000}",
            "mode": "simulation"
        }

    async def _delete_nat_one_to_one(self, uuid: str) -> Dict:
        """
        Supprime un NAT 1:1.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle delete_nat_one_to_one du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Suppression NAT 1:1: {uuid}")
        
        if self._api_client:
            try:
                response = self._api_client.delete_nat_one_to_one(uuid)
                
                if response.get('result') == 'deleted':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ NAT 1:1 {uuid} supprimé")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur suppression NAT 1:1: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "deleted", "uuid": uuid, "mode": "simulation"}

    # ========================================================================
    # Diagnostics & Logs
    # ========================================================================

    async def _get_firewall_log(
        self,
        limit: int = 100,
        **kwargs
    ) -> Dict:
        """
        Récupère les logs du firewall.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle get_firewall_log du client API avec filtres
        - Pas besoin d'apply (lecture seule)
        """
        logger.info(f"[OPNsense] Consultation logs (limit: {limit})")
        
        if self._api_client:
            try:
                return self._api_client.get_firewall_log(limit=limit, **kwargs)
            except Exception as e:
                logger.error(f"Erreur consultation logs: {e}")
                return {"status": "error", "message": str(e)}
        
        return {
            "total": 523,
            "logs": [
                {"action": "block", "src": "203.0.113.45", "dst": "192.168.1.10"},
                {"action": "pass", "src": "192.168.1.20", "dst": "8.8.8.8"}
            ],
            "mode": "simulation"
        }

    async def _get_firewall_states(self, filter: Optional[str] = None) -> Dict:
        """
        Récupère les états actifs (connexions).
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle get_firewall_states du client API
        - Pas besoin d'apply (lecture seule)
        """
        logger.info(f"[OPNsense] Consultation états{f': {filter}' if filter else ''}")
        
        if self._api_client:
            try:
                return self._api_client.get_firewall_states(filter)
            except Exception as e:
                logger.error(f"Erreur consultation états: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"total": 156, "states": [], "mode": "simulation"}

    async def _kill_firewall_states(self, filter: str) -> Dict:
        """
        Termine des connexions spécifiques.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle kill_firewall_states du client API
        - Pas besoin d'apply (action directe)
        """
        logger.info(f"[OPNsense] Kill états: {filter}")
        
        if self._api_client:
            try:
                response = self._api_client.kill_firewall_states(filter)
                logger.info(f"✓ États terminés: {response.get('count', 0)}")
                return response
            except Exception as e:
                logger.error(f"Erreur kill états: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "killed", "filter": filter, "count": 5, "mode": "simulation"}

    async def _flush_firewall_states(self) -> Dict:
        """
        Termine toutes les connexions.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle flush_firewall_states du client API
        - Pas besoin d'apply (action directe)
        """
        logger.info(f"[OPNsense] Flush tous les états")
        
        if self._api_client:
            try:
                response = self._api_client.flush_firewall_states()
                logger.info(f"✓ Tous les états terminés: {response.get('count', 0)}")
                return response
            except Exception as e:
                logger.error(f"Erreur flush états: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "flushed", "count": 156, "mode": "simulation"}

    async def _get_firewall_statistics(self) -> Dict:
        """
        Récupère les statistiques globales.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle get_firewall_statistics du client API
        - Pas besoin d'apply (lecture seule)
        """
        logger.info(f"[OPNsense] Consultation statistiques")
        
        if self._api_client:
            try:
                return self._api_client.get_firewall_statistics()
            except Exception as e:
                logger.error(f"Erreur consultation stats: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"packets": 1234567, "bytes": 9876543210, "mode": "simulation"}

    async def _get_rule_statistics(self) -> Dict:
        """
        Récupère les statistiques par règle.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle get_rule_statistics du client API
        - Pas besoin d'apply (lecture seule)
        """
        logger.info(f"[OPNsense] Consultation stats règles")
        
        if self._api_client:
            try:
                return self._api_client.get_rule_statistics()
            except Exception as e:
                logger.error(f"Erreur consultation stats règles: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"rules": [], "mode": "simulation"}

    # ========================================================================
    # Gestion de configuration
    # ========================================================================

    async def _apply_firewall_changes(self, rollback_timeout: int = 0) -> Dict:
        """
        Applique les modifications du firewall.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle apply_firewall_changes du client API
        - Gère le rollback timeout si spécifié
        """
        logger.info(f"[OPNsense] Application changements{f' (rollback: {rollback_timeout}s)' if rollback_timeout else ''}")
        
        if self._api_client:
            try:
                response = self._api_client.apply_firewall_changes(rollback_timeout)
                
                if response.get('status') == 'ok':
                    logger.info("✓ Changements appliqués avec succès")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur application changements: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "applied", "rollback_timeout": rollback_timeout, "mode": "simulation"}

    async def _cancel_firewall_rollback(self) -> Dict:
        """
        Annule le rollback automatique (confirme les changements).
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle cancel_firewall_rollback du client API
        """
        logger.info(f"[OPNsense] Annulation rollback")
        
        if self._api_client:
            try:
                response = self._api_client.cancel_firewall_rollback()
                logger.info("✓ Rollback annulé, changements confirmés")
                return response
            except Exception as e:
                logger.error(f"Erreur annulation rollback: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "confirmed", "mode": "simulation"}

    async def _revert_firewall_changes(self) -> Dict:
        """
        Annule les changements non appliqués.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle revert_firewall_changes du client API
        """
        logger.info(f"[OPNsense] Revert changements")
        
        if self._api_client:
            try:
                response = self._api_client.revert_firewall_changes()
                logger.info("✓ Changements annulés")
                return response
            except Exception as e:
                logger.error(f"Erreur revert: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "reverted", "mode": "simulation"}

    async def _create_firewall_savepoint(self, revision: Optional[str] = None) -> Dict:
        """
        Crée un point de sauvegarde.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle create_firewall_savepoint du client API
        """
        logger.info(f"[OPNsense] Création savepoint{f': {revision}' if revision else ''}")
        
        if self._api_client:
            try:
                response = self._api_client.create_firewall_savepoint(revision)
                logger.info(f"✓ Savepoint créé: {response.get('revision', 'auto')}")
                return response
            except Exception as e:
                logger.error(f"Erreur création savepoint: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "saved", "revision": revision or "auto", "mode": "simulation"}

    async def _get_interface_list(self) -> Dict:
        """
        Liste toutes les interfaces réseau.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle get_interface_list du client API
        - Pas besoin d'apply (lecture seule)
        """
        logger.info(f"[OPNsense] Liste interfaces")
        
        if self._api_client:
            try:
                return self._api_client.get_interface_list()
            except Exception as e:
                logger.error(f"Erreur liste interfaces: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"interfaces": ["wan", "lan", "opt1", "opt2"], "mode": "simulation"}

    # ========================================================================
    # Organisation
    # ========================================================================

    async def _create_category(self, name: str, **kwargs) -> Dict:
        """
        Crée une catégorie pour organiser les règles.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle create_category du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Création catégorie: {name}")
        
        if self._api_client:
            try:
                cat_data = {
                    "category": {
                        "name": name,
                        **{k: v for k, v in kwargs.items() if v is not None}
                    }
                }
                
                response = self._api_client.create_category(cat_data)
                
                if response.get('result') == 'saved':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Catégorie '{name}' créée")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur création catégorie: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "created", "uuid": f"cat-{hash(name) % 10000}", "mode": "simulation"}

    async def _delete_category(self, uuid: str) -> Dict:
        """
        Supprime une catégorie.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle delete_category du client API
        - Applique les changements
        """
        logger.info(f"[OPNsense] Suppression catégorie: {uuid}")
        
        if self._api_client:
            try:
                response = self._api_client.delete_category(uuid)
                
                if response.get('result') == 'deleted':
                    self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Catégorie {uuid} supprimée")
                
                return response
                
            except Exception as e:
                logger.error(f"Erreur suppression catégorie: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "deleted", "uuid": uuid, "mode": "simulation"}

    async def _list_available_categories(self) -> Dict:
        """
        Liste toutes les catégories disponibles.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle list_available_categories du client API
        - Pas besoin d'apply (lecture seule)
        """
        logger.info(f"[OPNsense] Liste catégories")
        
        if self._api_client:
            try:
                return self._api_client.list_available_categories()
            except Exception as e:
                logger.error(f"Erreur liste catégories: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"categories": [], "mode": "simulation"}

    async def _update_bogons(self) -> Dict:
        """
        Met à jour les listes de réseaux bogons.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle update_bogons du client API
        - Pas besoin d'apply (action directe)
        """
        logger.info(f"[OPNsense] Mise à jour bogons")
        
        if self._api_client:
            try:
                response = self._api_client.update_bogons()
                logger.info("✓ Bogons mis à jour")
                return response
            except Exception as e:
                logger.error(f"Erreur mise à jour bogons: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"status": "updated", "mode": "simulation"}

    # ========================================================================
    # GeoIP
    # ========================================================================

    async def _list_geoip_countries(self) -> Dict:
        """
        Liste tous les pays disponibles pour GeoIP.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle list_geoip_countries du client API
        - Pas besoin d'apply (lecture seule)
        """
        logger.info(f"[OPNsense] Liste pays GeoIP")
        
        if self._api_client:
            try:
                return self._api_client.list_geoip_countries()
            except Exception as e:
                logger.error(f"Erreur liste pays GeoIP: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"countries": ["FR", "US", "DE", "GB", "CN", "RU"], "mode": "simulation"}

    async def _get_geoip_database(self) -> Dict:
        """
        Récupère les informations sur la base GeoIP.
        
        IMPLÉMENTATION RÉFÉRENCE :
        - Appelle get_geoip_database du client API
        - Pas besoin d'apply (lecture seule)
        """
        logger.info(f"[OPNsense] Info base GeoIP")
        
        if self._api_client:
            try:
                return self._api_client.get_geoip_database()
            except Exception as e:
                logger.error(f"Erreur info base GeoIP: {e}")
                return {"status": "error", "message": str(e)}
        
        return {"version": "2024.01", "last_update": "2024-01-15", "mode": "simulation"}
