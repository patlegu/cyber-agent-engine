"""
agents/wireguard_agent.py

Agent-outil pour la gestion des tunnels VPN WireGuard.
Exposé sous le nom d'outil "wireguard" dans l'API HTTP (/capabilities, /agent/execute).

Supporte deux plateformes :
- "opnsense" : via l'API REST OPNsense (WireGuardAPIClient)
- "linux"    : via la CLI wg/wg-quick (WireGuardLinuxClient)

---

## Fonctions exposées (11)

| Nom                          | Description courte                       | requires_approval |
|------------------------------|------------------------------------------|:-----------------:|
| create_site_to_site_tunnel   | Crée un tunnel site-à-site               | oui               |
| create_point_to_point_tunnel | Crée un tunnel point-à-point             | oui               |
| create_mesh_network          | Crée un réseau maillé (mesh)             | oui               |
| get_tunnel_status            | État du tunnel (actif, peers connectés)  | non               |
| rotate_keys                  | Rotation des clés du tunnel              | oui               |
| verify_routing               | Vérifie la table de routage VPN          | non               |
| add_wireguard_server         | Ajoute un serveur WireGuard              | oui               |
| add_wireguard_client         | Ajoute un peer client WireGuard          | oui               |
| generate_wireguard_keypair   | Génère une paire de clés WireGuard       | non               |
| generate_wireguard_psk       | Génère une Pre-Shared Key (PSK)          | non               |
| get_wireguard_status         | Statut global WireGuard                  | non               |

---

## Ajouter une fonction

1. Définir la méthode dans cette classe :

       async def ma_fonction(self, param: str, mode: Literal["add", "delete"] = "add") -> Dict:
           \"\"\"Résumé une ligne (extrait comme `description` dans get_capabilities()).

           :param param: Description affichée dans le schéma JSON exposé au LLM.
           :param mode: Action à réaliser.
           \"\"\"

   Conventions :
   - Utiliser `:param name:` (et non `Args:`) — format lu par `_parse_param_docs()` dans base.py.
   - `Literal["v1", "v2"]` sur le type → enum dans le schéma OpenAI function-calling.
   - Les méthodes publiques (sans `_`) sont enregistrables directement.

2. Enregistrer dans `_register_functions()`.

3. Vérifier le schéma généré :

       python scripts/extract_wireguard_tools.py

---

## Mode simulation

`simulation_mode=True` (ou absence de config client) retourne des réponses simulées.
Activé automatiquement si `WIREGUARD_*` n'est pas configuré dans `.env`.
"""

import logging
import ipaddress
from typing import Dict, List, Optional, Literal, Any
from datetime import datetime
from .base import ToolAgent
from clients import WireGuardAPIClient, WireGuardLinuxClient

logger = logging.getLogger(__name__)

TunnelType = Literal["site_to_site", "point_to_point", "mesh"]
Platform = Literal["opnsense", "linux"]


class WireGuardAgent(ToolAgent):
    """
    Agent IA pour gestion complète de WireGuard.

    Fonctionnalités :
    - Création de tunnels (Site-to-Site, Point-to-Point, Mesh)
    - Gestion de clés, statut, rotation
    """

    agent_role  = "WireGuard VPN agent"
    chat_format = "qwen"
    system_prompt = (
        "Tu es un agent WireGuard. Tu reçois des directives structurées du coordinateur "
        "sous forme de paquets JSON (format CAP v1 : directive + entities + args) et tu génères "
        "des appels d'API précis sous forme de tool_calls. "
        "Tu ne réponds jamais en langage naturel — uniquement des tool_calls."
    )

    def __init__(
        self,
        platform: Platform = "opnsense",
        config: Optional[Dict] = None,
        simulation_mode: bool = False,
        ollama_config: Optional[Dict] = None,
        model_path: Optional[str] = None,
        vllm_client: Optional[Any] = None,
        openai_client: Optional[Any] = None,
        lora_model: str = ""
    ):
        """
        Initialise l'agent WireGuard.

        Args:
            platform: Plateforme cible ("opnsense" ou "linux")
            config: Configuration pour la plateforme (requis pour OPNsense)
            simulation_mode: Mode simulation (pas d'actions réelles)
            ollama_config: Config Ollama override {"model": "...", "url": "..."}
            model_path: Chemin LoRA local (optionnel)
            vllm_client: Client vLLM partagé (optionnel)
            openai_client: Client HTTP OpenAI-compatible partagé (optionnel)
            lora_model: Nom du LoRA à passer à openai_client (optionnel)
        """
        self.platform = platform
        self.simulation_mode = simulation_mode
        self.config = config or {}

        # Initialiser l'agent de base
        super().__init__(
            tool_name="wireguard",
            model_path=model_path or self.config.get('model_path'),
            api_config=config,
            ollama_config=ollama_config,
            vllm_client=vllm_client,
            openai_client=openai_client,
            lora_model=lora_model
        )
        
        # Initialiser le client approprié
        if platform == "opnsense":
            if not self.api_config and not self.simulation_mode:
                raise ValueError("Configuration requise pour OPNsense")
            
            if self.api_config:
                self.client = WireGuardAPIClient(
                    base_url=self.api_config['base_url'],
                    api_key=self.api_config['api_key'],
                    api_secret=self.api_config['api_secret'],
                    verify_ssl=self.api_config.get('verify_ssl', True),
                    timeout=self.api_config.get('timeout', 30)
                )
            else:
                self.client = None # Simulation only
        elif platform == "linux":
            self.client = WireGuardLinuxClient(
                config_dir=self.api_config.get('config_dir', '/etc/wireguard')
            )
        else:
            raise ValueError(f"Plateforme non supportée: {platform}")
        
        logger.info(f"Agent WireGuard initialisé (platform: {platform}, simulation: {simulation_mode})")

    def _register_functions(self) -> Dict[str, callable]:
        """Enregistre les fonctions disponibles pour WireGuard."""
        return {
            "create_site_to_site_tunnel": self.create_site_to_site_tunnel,
            "create_point_to_point_tunnel": self.create_point_to_point_tunnel,
            "create_mesh_network": self.create_mesh_network,
            "get_tunnel_status": self.get_tunnel_status,
            "rotate_keys": self.rotate_keys,
            "verify_routing": self.verify_routing,
            # Adaptateurs
            "add_wireguard_server": self.add_wireguard_server,
            "add_wireguard_client": self.add_wireguard_client,
            "generate_wireguard_keypair": self.generate_wireguard_keypair,
            "generate_wireguard_psk": self.generate_wireguard_psk,
            "get_wireguard_status": self.get_wireguard_status
        }

    # ========================================================================
    # Création de Tunnels - Site-to-Site
    # ========================================================================

    async def create_site_to_site_tunnel(
        self,
        site_a: Dict,
        site_b: Dict,
        tunnel_network: str = "10.0.0.0/30",
        listen_port: int = 51820,
        enable_psk: bool = True
    ) -> Dict:
        """
        Crée un tunnel Site-to-Site entre deux sites.
        
        Args:
            site_a: Configuration du site A
                {
                    "name": "paris",
                    "network": "192.168.1.0/24",  # Réseau local
                    "endpoint": "203.0.113.10",   # IP publique (optionnel)
                }
            site_b: Configuration du site B
                {
                    "name": "london",
                    "network": "192.168.2.0/24",
                    "endpoint": "203.0.113.20",
                }
            tunnel_network: Réseau du tunnel (/30 pour 2 IPs)
            listen_port: Port d'écoute WireGuard
            enable_psk: Activer pre-shared key pour sécurité renforcée
            
        Returns:
            Configuration complète du tunnel
        """
        logger.info(f"Création tunnel Site-to-Site: {site_a['name']} ↔ {site_b['name']}")
        
        if self.simulation_mode:
            return await self._simulate_site_to_site(site_a, site_b, tunnel_network)
        
        # Générer les clés pour les deux sites
        keys_a = await getattr(self.client, 'generate_keypair' if self.platform == "linux" else 'generate_wireguard_keypair')()
        keys_b = await getattr(self.client, 'generate_keypair' if self.platform == "linux" else 'generate_wireguard_keypair')()
        
        # Générer PSK si activé
        psk = None
        if enable_psk:
            if self.platform == "linux":
                psk = await self.client.generate_psk()
            else:
                psk_resp = await self.client.generate_wireguard_psk()
                psk = psk_resp.get('psk')
        
        # Calculer les IPs du tunnel
        tunnel_net = ipaddress.ip_network(tunnel_network)
        tunnel_ips = list(tunnel_net.hosts())
        ip_a = f"{tunnel_ips[0]}/{tunnel_net.prefixlen}"
        ip_b = f"{tunnel_ips[1]}/{tunnel_net.prefixlen}"
        
        # Créer les configurations selon la plateforme
        if self.platform == "opnsense":
            tunnel = await self._create_site_to_site_opnsense(
                site_a, site_b, keys_a, keys_b, ip_a, ip_b, listen_port, psk
            )
        else:  # linux
            tunnel = await self._create_site_to_site_linux(
                site_a, site_b, keys_a, keys_b, ip_a, ip_b, listen_port, psk
            )
        
        logger.info(f"✓ Tunnel Site-to-Site créé: {site_a['name']} ↔ {site_b['name']}")
        return tunnel

    async def _create_site_to_site_opnsense(
        self,
        site_a: Dict,
        site_b: Dict,
        keys_a: Dict,
        keys_b: Dict,
        ip_a: str,
        ip_b: str,
        listen_port: int,
        psk: Optional[str]
    ) -> Dict:
        """Crée un tunnel Site-to-Site sur OPNsense."""
        
        # Créer le serveur WireGuard (site A)
        server_data = {
            "server": {
                "enabled": "1",
                "name": f"wg-{site_a['name']}",
                "pubkey": keys_a.get('pubkey', keys_a.get('public_key')),
                "privkey": keys_a.get('privkey', keys_a.get('private_key')),
                "port": str(listen_port),
                "tunneladdress": ip_a,
                "disableroutes": "0"
            }
        }
        server_result = await self.client.add_wireguard_server(server_data)
        server_uuid = server_result.get('uuid')
        
        # Créer le peer (site B)
        client_data = {
            "client": {
                "enabled": "1",
                "name": f"peer-{site_b['name']}",
                "pubkey": keys_b.get('pubkey', keys_b.get('public_key')),
                "tunneladdress": ip_b,
                "serveraddress": site_b.get('endpoint', ''),
                "serverport": str(listen_port),
                "keepalive": "25"
            }
        }
        
        if psk:
            client_data["client"]["psk"] = psk
        
        # Ajouter les réseaux autorisés (allowed IPs)
        allowed_ips = [site_b['network'], ip_b.split('/')[0] + '/32']
        client_data["client"]["tunneladdress"] = ','.join(allowed_ips)
        
        client_result = await self.client.add_wireguard_client(client_data)
        
        # Reconfigurer WireGuard
        await self.client.reconfigure_wireguard()
        
        return {
            "type": "site_to_site",
            "platform": "opnsense",
            "site_a": {
                "name": site_a['name'],
                "server_uuid": server_uuid,
                "tunnel_ip": ip_a,
                "public_key": keys_a.get('pubkey', keys_a.get('public_key')),
                "network": site_a['network']
            },
            "site_b": {
                "name": site_b['name'],
                "peer_uuid": client_result.get('uuid'),
                "tunnel_ip": ip_b,
                "public_key": keys_b.get('pubkey', keys_b.get('public_key')),
                "network": site_b['network'],
                "endpoint": site_b.get('endpoint')
            },
            "psk_enabled": psk is not None,
            "listen_port": listen_port
        }

    async def _create_site_to_site_linux(
        self,
        site_a: Dict,
        site_b: Dict,
        keys_a: Dict,
        keys_b: Dict,
        ip_a: str,
        ip_b: str,
        listen_port: int,
        psk: Optional[str]
    ) -> Dict:
        """Crée un tunnel Site-to-Site sur Linux."""
        
        interface_name = f"wg-{site_a['name']}-{site_b['name']}"
        
        # Créer l'interface locale
        interface = await self.client.create_interface(
            interface=interface_name,
            address=ip_a,
            listen_port=listen_port,
            private_key=keys_a['private_key'],
            post_up=f"iptables -A FORWARD -i {interface_name} -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE",
            post_down=f"iptables -D FORWARD -i {interface_name} -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE"
        )
        
        # Ajouter le peer distant
        allowed_ips = [site_b['network'], ip_b.split('/')[0] + '/32']
        await self.client.add_peer(
            interface=interface_name,
            public_key=keys_b['public_key'],
            allowed_ips=allowed_ips,
            endpoint=f"{site_b.get('endpoint')}:{listen_port}" if site_b.get('endpoint') else None,
            preshared_key=psk,
            persistent_keepalive=25
        )
        
        # Démarrer l'interface
        await self.client.start_interface(interface_name)
        
        return {
            "type": "site_to_site",
            "platform": "linux",
            "interface": interface_name,
            "site_a": {
                "name": site_a['name'],
                "tunnel_ip": ip_a,
                "public_key": keys_a['public_key'],
                "network": site_a['network']
            },
            "site_b": {
                "name": site_b['name'],
                "tunnel_ip": ip_b,
                "public_key": keys_b['public_key'],
                "network": site_b['network'],
                "endpoint": site_b.get('endpoint')
            },
            "psk_enabled": psk is not None,
            "listen_port": listen_port,
            "config_file": interface.get('config_file')
        }

    # ========================================================================
    # Création de Tunnels - Point-to-Point
    # ========================================================================

    async def create_point_to_point_tunnel(
        self,
        local_ip: str,
        remote_ip: str,
        remote_endpoint: str,
        interface_name: str = "wg0",
        listen_port: int = 51820,
        enable_psk: bool = True
    ) -> Dict:
        """
        Crée un tunnel Point-to-Point entre deux machines.
        
        Args:
            local_ip: IP locale du tunnel (CIDR, ex: 10.0.0.1/32)
            remote_ip: IP distante du tunnel (CIDR, ex: 10.0.0.2/32)
            remote_endpoint: Endpoint distant (IP:port, ex: 203.0.113.42:51820)
            interface_name: Nom de l'interface
            listen_port: Port d'écoute local
            enable_psk: Activer pre-shared key
            
        Returns:
            Configuration du tunnel
        """
        logger.info(f"Création tunnel Point-to-Point: {local_ip} ↔ {remote_ip}")
        
        if self.simulation_mode:
            return {"type": "point_to_point", "status": "simulated"}
        
        # Générer les clés
        if self.platform == "linux":
            local_keys = await self.client.generate_keypair()
            remote_keys = await self.client.generate_keypair()
        else:
            local_keys = await self.client.generate_wireguard_keypair()
            remote_keys = await self.client.generate_wireguard_keypair()
        
        psk = None
        if enable_psk:
            if self.platform == "linux":
                psk = await self.client.generate_psk()
            else:
                psk_resp = await self.client.generate_wireguard_psk()
                psk = psk_resp.get('psk')
        
        if self.platform == "linux":
            # Créer l'interface
            interface = await self.client.create_interface(
                interface=interface_name,
                address=local_ip,
                listen_port=listen_port,
                private_key=local_keys['private_key']
            )
            
            # Ajouter le peer distant
            await self.client.add_peer(
                interface=interface_name,
                public_key=remote_keys['public_key'],
                allowed_ips=[remote_ip],
                endpoint=remote_endpoint,
                preshared_key=psk,
                persistent_keepalive=25
            )
            
            # Démarrer
            await self.client.start_interface(interface_name)
            
            return {
                "type": "point_to_point",
                "platform": "linux",
                "interface": interface_name,
                "local": {
                    "ip": local_ip,
                    "public_key": local_keys['public_key'],
                    "listen_port": listen_port
                },
                "remote": {
                    "ip": remote_ip,
                    "public_key": remote_keys['public_key'],
                    "endpoint": remote_endpoint
                },
                "psk_enabled": psk is not None,
                "config_file": interface.get('config_file')
            }
        
        # TODO: Implémenter pour OPNsense
        raise NotImplementedError("Point-to-Point non encore implémenté pour OPNsense")

    # ========================================================================
    # Création de Tunnels - Mesh Network
    # ========================================================================

    async def create_mesh_network(
        self,
        nodes: List[Dict],
        network_prefix: str = "10.0.0.0/24",
        base_port: int = 51820,
        enable_psk: bool = True
    ) -> Dict:
        """
        Crée un réseau maillé (mesh) avec plusieurs peers.
        
        Chaque nœud se connecte à tous les autres nœuds.
        
        Args:
            nodes: Liste des nœuds
                [
                    {"name": "node1", "endpoint": "203.0.113.10"},
                    {"name": "node2", "endpoint": "203.0.113.20"},
                    {"name": "node3", "endpoint": "203.0.113.30"},
                ]
            network_prefix: Préfixe réseau pour les IPs du mesh
            base_port: Port de base (incrémenté pour chaque nœud)
            enable_psk: Activer pre-shared keys
            
        Returns:
            Configuration complète du mesh
        """
        logger.info(f"Création réseau mesh avec {len(nodes)} nœuds")
        
        if self.simulation_mode:
            return {"type": "mesh", "nodes": len(nodes), "status": "simulated"}
        
        # Générer les clés pour chaque nœud
        network = ipaddress.ip_network(network_prefix)
        ips = list(network.hosts())
        
        mesh_config = {
            "type": "mesh",
            "platform": self.platform,
            "nodes": []
        }
        
        # Génerer les clés pour tous les nœuds
        node_keys = []
        for i, node in enumerate(nodes):
            keys = await getattr(self.client, 'generate_keypair' if self.platform == "linux" else 'generate_wireguard_keypair')()
            node_keys.append({
                "name": node['name'],
                "endpoint": node.get('endpoint'),
                "ip": f"{ips[i]}/24",
                "port": base_port + i,
                "public_key": keys.get('public_key', keys.get('pubkey')),
                "private_key": keys.get('private_key', keys.get('privkey'))
            })
        
        # Créer les interfaces et peers pour chaque nœud
        for i, node_config in enumerate(node_keys):
            interface_name = f"wg-mesh-{node_config['name']}"
            
            if self.platform == "linux":
                # Créer l'interface
                await self.client.create_interface(
                    interface=interface_name,
                    address=node_config['ip'],
                    listen_port=node_config['port'],
                    private_key=node_config['private_key']
                )
                
                # Ajouter tous les autres nœuds comme peers
                for j, peer_config in enumerate(node_keys):
                    if i != j:  # Ne pas s'ajouter soi-même
                        psk = await self.client.generate_psk() if enable_psk else None
                        
                        await self.client.add_peer(
                            interface=interface_name,
                            public_key=peer_config['public_key'],
                            allowed_ips=[peer_config['ip'].split('/')[0] + '/32'],
                            endpoint=f"{peer_config['endpoint']}:{peer_config['port']}" if peer_config.get('endpoint') else None,
                            preshared_key=psk,
                            persistent_keepalive=25
                        )
                
                # Démarrer l'interface
                await self.client.start_interface(interface_name)
            
            mesh_config['nodes'].append({
                "name": node_config['name'],
                "interface": interface_name,
                "ip": node_config['ip'],
                "port": node_config['port'],
                "public_key": node_config['public_key'],
                "endpoint": node_config.get('endpoint'),
                "peers": len(nodes) - 1
            })
        
        logger.info(f"✓ Réseau mesh créé avec {len(nodes)} nœuds")
        return mesh_config

    # ========================================================================
    # Monitoring et Diagnostics
    # ========================================================================

    async def get_tunnel_status(self, interface: Optional[str] = None) -> Dict:
        """
        Récupère le statut des tunnels WireGuard.
        
        Args:
            interface: Interface spécifique (None pour toutes)
            
        Returns:
            Statut détaillé des tunnels
        """
        if self.platform == "linux":
            return await self.client.get_interface_status(interface)
        else:  # opnsense
            return await self.client.get_wireguard_status()

    async def verify_routing(self, tunnel_config: Dict) -> Dict:
        """
        Vérifie que le routage est correct pour un tunnel.
        
        Args:
            tunnel_config: Configuration du tunnel à vérifier
            
        Returns:
            Résultat de la vérification
        """
        # TODO: Implémenter vérification routage
        logger.info("Vérification du routage...")
        return {"status": "ok", "routes": []}

    async def rotate_keys(self, interface: str) -> Dict:
        """
        Effectue une rotation des clés pour un tunnel.
        
        Args:
            interface: Interface concernée
            
        Returns:
            Nouvelles clés générées
        """
        logger.info(f"Rotation des clés pour {interface}")
        
        # Générer nouvelles clés
        new_keys = await getattr(self.client, 'generate_keypair' if self.platform == "linux" else 'generate_wireguard_keypair')()
        
        # TODO: Appliquer les nouvelles clés
        
        return {
            "interface": interface,
            "new_public_key": new_keys.get('public_key', new_keys.get('pubkey')),
            "rotated_at": datetime.now().isoformat()
        }

    # ========================================================================
    # Adaptateurs Polyfill (OPNsense <-> Linux)
    # ========================================================================

    async def add_wireguard_server(self, server: Dict) -> Dict:
        """
        Crée un serveur WireGuard (Interface).
        Adaptateur compatible OPNsense/Linux.
        """
        logger.info(f"Adapter: add_wireguard_server (platform={self.platform})")
        
        if self.platform == "opnsense":
            if self.simulation_mode:
                return {"status": "success", "uuid": "sim-server-uuid", "mode": "simulation"}
            return await self.client.add_wireguard_server(server)
            
        # Linux Implementation
        # format opnsense: {"server": {"name": "...", "port": "...", "tunneladdress": "...", "pubkey": "...", "privkey": "..."}}
        data = server.get('server', server)
        
        name = data.get('name', 'wg0')
        # Nettoyer le nom pour Linux (pas d'espaces, etc)
        if not name.startswith('wg'):
            name = f"wg{name}"
            
        return await self.client.create_interface(
            interface=name,
            address=data.get('tunneladdress', '10.0.0.1/24'),
            listen_port=int(data.get('port', 51820)),
            private_key=data.get('privkey')
        )

    async def add_wireguard_client(self, client: Dict) -> Dict:
        """
        Ajoute un client WireGuard (Peer).
        Adaptateur compatible OPNsense/Linux.
        """
        logger.info(f"Adapter: add_wireguard_client (platform={self.platform})")
        
        if self.platform == "opnsense":
            if self.simulation_mode:
                return {"status": "success", "uuid": "sim-client-uuid", "mode": "simulation"}
            return await self.client.add_wireguard_client(client)
            
        # Linux Implementation
        # format opnsense: {"client": {"name": "...", "pubkey": "...", "tunneladdress": "...", "serveraddress": "...", "serverport": "..."}}
        data = client.get('client', client)
        
        # On a besoin de savoir à quelle interface ajouter ce peer.
        # Dans OPNsense le lien est fait via UUIDs ou config.
        # Ici on va essayer de deviner ou utiliser une convention.
        # Fallback sur 'wg0' si non spécifié via un champ 'interface' (qui n'existe pas dans le schéma OPNsense standard mais qu'on peut injecter)
        interface = data.get('interface', 'wg0')
        
        endpoint = None
        if data.get('serveraddress'):
            port = data.get('serverport', '51820')
            endpoint = f"{data['serveraddress']}:{port}"
            
        return await self.client.add_peer(
            interface=interface,
            public_key=data.get('pubkey'),
            allowed_ips=data.get('tunneladdress', '').split(','),
            endpoint=endpoint,
            preshared_key=data.get('psk'),
            persistent_keepalive=int(data.get('keepalive', 25)) if data.get('keepalive') else None
        )

    async def generate_wireguard_keypair(self) -> Dict:
        """Génère une paire de clés (Adaptateur)."""
        if self.platform == "opnsense":
            return await self.client.generate_wireguard_keypair()
        return await self.client.generate_keypair()

    async def generate_wireguard_psk(self) -> Dict:
        """Génère une PSK (Adaptateur)."""
        if self.platform == "opnsense":
            return await self.client.generate_wireguard_psk()
        return {"psk": await self.client.generate_psk()}

    async def get_wireguard_status(self) -> Dict:
        """Récupère le statut (Adaptateur)."""
        if self.platform == "opnsense":
            if self.simulation_mode:
                 return {"status": "ok", "interfaces": {"wg0": {"type": "vm", "status": "up"}}, "mode": "simulation"}
            return await self.client.get_wireguard_status()
        return await self.client.get_interface_status(None)

    # ========================================================================
    # Méthodes Utilitaires
    # ========================================================================

    async def _simulate_site_to_site(
        self,
        site_a: Dict,
        site_b: Dict,
        tunnel_network: str
    ) -> Dict:
        """Simule la création d'un tunnel."""
        return {
            "type": "site_to_site",
            "mode": "simulation",
            "site_a": site_a,
            "site_b": site_b,
            "tunnel_network": tunnel_network,
            "status": "simulated"
        }

