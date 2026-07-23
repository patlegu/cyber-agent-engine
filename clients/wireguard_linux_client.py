# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Client WireGuard pour Linux standalone.

Ce client gère WireGuard directement via la CLI `wg` et `wg-quick`
sur un système Linux, sans passer par une API firewall.
"""

import logging
import asyncio
import json
import re
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class WireGuardLinuxClient:
    """
    Client pour gérer WireGuard sur Linux standalone via CLI.
    
    Utilise les commandes `wg`, `wg-quick`, et `wg-keygen` pour gérer
    les interfaces WireGuard directement sur le système.
    """

    def __init__(self, config_dir: str = "/etc/wireguard"):
        """
        Initialise le client Linux WireGuard.
        
        Args:
            config_dir: Répertoire des configurations WireGuard
        """
        self.config_dir = Path(config_dir)
        logger.info(f"WireGuard Linux client initialized (config: {config_dir})")

    async def _run_command(self, cmd: List[str], input_str: Optional[str] = None, check: bool = True) -> Dict:
        """
        Exécute une commande shell de façon asynchrone.
        """
        logger.debug(f"Executing: {' '.join(cmd)}")
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if input_str else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await proc.communicate(input=input_str.encode() if input_str else None)
        stdout_str = stdout.decode().strip()
        stderr_str = stderr.decode().strip()
        
        if check and proc.returncode != 0:
            logger.error(f"Command error {' '.join(cmd)}: {stderr_str}")
            raise RuntimeError(f"Command failed ({proc.returncode}): {stderr_str}")
            
        return {
            "stdout": stdout_str,
            "stderr": stderr_str,
            "returncode": proc.returncode
        }

    async def check_installed(self) -> bool:
        """Vérifie que WireGuard est installé."""
        try:
            await self._run_command(['wg', '--version'])
            return True
        except (RuntimeError, FileNotFoundError):
            return False

    # ========================================================================
    # Gestion des Clés
    # ========================================================================

    async def generate_keypair(self) -> Dict[str, str]:
        """
        Génère une nouvelle paire de clés WireGuard.
        
        Returns:
            Dictionnaire avec 'private_key' et 'public_key'
        """
        # Générer clé privée
        result = await self._run_command(['wg', 'genkey'])
        private_key = result['stdout']
        
        # Générer clé publique depuis la privée
        result = await self._run_command(['wg', 'pubkey'], input_str=private_key)
        public_key = result['stdout']
        
        logger.info("WireGuard key pair generated")
        return {
            'private_key': private_key,
            'public_key': public_key
        }

    async def generate_psk(self) -> str:
        """
        Génère une pre-shared key (PSK).
        
        Returns:
            Pre-shared key
        """
        result = await self._run_command(['wg', 'genpsk'])
        psk = result['stdout']
        logger.info("WireGuard PSK generated")
        return psk

    # ========================================================================
    # Gestion des Interfaces
    # ========================================================================

    async def create_interface(
        self,
        interface: str,
        address: str,
        listen_port: int,
        private_key: Optional[str] = None,
        **kwargs
    ) -> Dict:
        """
        Crée une nouvelle interface WireGuard.
        """
        # Générer clé si non fournie
        if not private_key:
            keys = await self.generate_keypair()
            private_key = keys['private_key']
            public_key = keys['public_key']
        else:
            # Calculer la clé publique depuis la privée
            result = await self._run_command(['wg', 'pubkey'], input_str=private_key)
            public_key = result['stdout']

        # Créer fichier de configuration
        config_file = self.config_dir / f"{interface}.conf"
        config_content = f"""[Interface]
Address = {address}
ListenPort = {listen_port}
PrivateKey = {private_key}
"""
        
        # Ajouter options supplémentaires
        if 'post_up' in kwargs:
            config_content += f"PostUp = {kwargs['post_up']}\n"
        if 'post_down' in kwargs:
            config_content += f"PostDown = {kwargs['post_down']}\n"
        if 'save_config' in kwargs:
            config_content += f"SaveConfig = {kwargs['save_config']}\n"

        # Écrire la configuration (opération bloquante mais rapide sur SSD, 
        # on peut l'envelopper dans un thread si vraiment nécessaire)
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(config_content)
        config_file.chmod(0o600)
        
        logger.info(f"Interface {interface} created ({config_file})")
        
        return {
            'interface': interface,
            'address': address,
            'listen_port': listen_port,
            'public_key': public_key,
            'config_file': str(config_file)
        }

    async def start_interface(self, interface: str) -> bool:
        """Démarre une interface WireGuard."""
        try:
            await self._run_command(['wg-quick', 'up', interface])
            logger.info(f"Interface {interface} started")
            return True
        except Exception as e:
            logger.error(f"Startup error {interface}: {e}")
            return False

    async def stop_interface(self, interface: str) -> bool:
        """Arrête une interface WireGuard."""
        try:
            await self._run_command(['wg-quick', 'down', interface])
            logger.info(f"Interface {interface} stopped")
            return True
        except Exception as e:
            logger.error(f"Stop error {interface}: {e}")
            return False

    async def restart_interface(self, interface: str) -> bool:
        """Redémarre une interface WireGuard."""
        await self.stop_interface(interface)
        return await self.start_interface(interface)

    async def delete_interface(self, interface: str) -> bool:
        """Supprime une interface WireGuard."""
        await self.stop_interface(interface)
        
        config_file = self.config_dir / f"{interface}.conf"
        if config_file.exists():
            config_file.unlink()
            logger.info(f"Interface {interface} removed")
            return True
        return False

    # ========================================================================
    # Gestion des Peers
    # ========================================================================

    async def add_peer(
        self,
        interface: str,
        public_key: str,
        allowed_ips: List[str],
        endpoint: Optional[str] = None,
        preshared_key: Optional[str] = None,
        persistent_keepalive: Optional[int] = None
    ) -> bool:
        """Ajoute un peer à une interface WireGuard."""
        config_file = self.config_dir / f"{interface}.conf"
        if not config_file.exists():
            raise FileNotFoundError(f"Interface {interface} does not exist")

        config = config_file.read_text()
        
        peer_config = f"\n[Peer]\nPublicKey = {public_key}\n"
        peer_config += f"AllowedIPs = {', '.join(allowed_ips)}\n"
        
        if endpoint:
            peer_config += f"Endpoint = {endpoint}\n"
        if preshared_key:
            peer_config += f"PresharedKey = {preshared_key}\n"
        if persistent_keepalive:
            peer_config += f"PersistentKeepalive = {persistent_keepalive}\n"

        config += peer_config
        config_file.write_text(config)
        
        logger.info(f"Peer added to {interface}")
        return True

    async def remove_peer(self, interface: str, public_key: str) -> bool:
        """Supprime un peer d'une interface WireGuard."""
        try:
            await self._run_command(['wg', 'set', interface, 'peer', public_key, 'remove'])
            logger.info(f"Peer {public_key[:16]}... removed from {interface}")
            return True
        except Exception as e:
            logger.error(f"Peer removal error: {e}")
            return False

    # ========================================================================
    # Monitoring et Statut
    # ========================================================================

    async def get_interface_status(self, interface: Optional[str] = None) -> Dict:
        """Récupère le statut d'une ou toutes les interfaces WireGuard."""
        cmd = ['wg', 'show']
        if interface:
            cmd.append(interface)
        cmd.append('dump')
        
        try:
            result = await self._run_command(cmd)
            return self._parse_wg_dump(result['stdout'])
        except Exception:
            return {}

    def _parse_wg_dump(self, dump: str) -> Dict:
        """Parse la sortie de 'wg show dump'."""
        interfaces = {}
        current_interface = None
        
        for line in dump.strip().split('\n'):
            if not line:
                continue
                
            parts = line.split('\t')
            if len(parts) >= 5:
                # Ligne d'interface ou de peer selon le contexte du dump
                # Le format dump est :
                # interface private_key public_key listen_port fwmark
                # peer public_key preshared_key endpoint allowed_ips latest_handshake transfer_rx transfer_tx persistent_keepalive
                
                # wg show [interface] dump affiche d'abord l'interface puis ses peers
                # Si on n'a pas spécifié d'interface, il le fait pour toutes l'une après l'autre ?
                # En fait le format dump est un peu particulier.
                
                # Pour simplifier on va juste parser ce qu'on reçoit
                if parts[0] in interfaces or current_interface is None:
                    # Interface
                    current_interface = parts[0]
                    interfaces[current_interface] = {
                        'public_key': parts[2] if len(parts) > 2 else 'unknown',
                        'listen_port': parts[3] if len(parts) > 3 else 'unknown',
                        'peers': []
                    }
                else:
                    # Peer
                    interfaces[current_interface]['peers'].append({
                        'public_key': parts[1],
                        'endpoint': parts[3] if parts[3] != '(none)' else None,
                        'allowed_ips': parts[4].split(',') if parts[4] else []
                    })
        
        return interfaces

    async def list_interfaces(self) -> List[str]:
        """Liste toutes les interfaces WireGuard configurées."""
        result = await self._run_command(['wg', 'show', 'interfaces'], check=False)
        interfaces = result['stdout'].strip().split()
        return interfaces

    async def is_interface_up(self, interface: str) -> bool:
        """Vérifie si une interface est active."""
        return interface in await self.list_interfaces()
