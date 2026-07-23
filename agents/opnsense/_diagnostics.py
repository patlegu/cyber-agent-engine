# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Diagnostics & Logs — 7 méthodes (read-only + kill states).
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class DiagnosticsMixin:

    async def _get_system_status(self) -> Dict:
        """Récupère l'état de santé du système (Polyfill multi-plateforme)."""
        logger.info(f"[Polyfill] Retrieving status (platform={self.platform})")

        if not self._api_client:
            return {"status": "Healthy", "mode": "simulation"}

        if self.platform == "linux":
            return await self._api_client.get_system_health()
        elif self.platform == "pfsense":
            return await self._api_client.get_system_stats()

        try:
            return {"system": {"platform": "opnsense", "status": "Healthy"}}
        except Exception as e:
            logger.error(f"Erreur status OPNsense: {e}")
            return {"status": "error", "message": str(e)}

    async def _get_firewall_log(self, limit: int = 100, **kwargs) -> Dict:
        """Récupère les logs du firewall."""
        logger.info(f"[OPNsense] Consultation logs (limit: {limit})")

        if self._api_client:
            try:
                return await self._api_client.get_firewall_log(limit=limit, **kwargs)
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
        """Récupère les états actifs (connexions)."""
        logger.info(f"[OPNsense] Checking states{f': {filter}' if filter else ''}")

        if self._api_client:
            try:
                return await self._api_client.get_firewall_states(filter)
            except Exception as e:
                logger.error(f"State check error: {e}")
                return {"status": "error", "message": str(e)}

        return {"total": 156, "states": [], "mode": "simulation"}

    async def _kill_firewall_states(self, filter: str) -> Dict:
        """Termine des connexions spécifiques."""
        logger.info(f"[OPNsense] Killing states: {filter}")

        if self._api_client:
            try:
                response = await self._api_client.kill_firewall_states(filter)
                logger.info(f"✓ States terminated: {response.get('count', 0)}")
                return response
            except Exception as e:
                logger.error(f"State kill error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "killed", "filter": filter, "count": 5, "mode": "simulation"}

    async def _flush_firewall_states(self) -> Dict:
        """Termine toutes les connexions."""
        logger.info("[OPNsense] Flushing all states")

        if self._api_client:
            try:
                response = await self._api_client.flush_firewall_states()
                logger.info(f"✓ All states terminated: {response.get('count', 0)}")
                return response
            except Exception as e:
                logger.error(f"State flush error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "flushed", "count": 156, "mode": "simulation"}

    async def _get_firewall_statistics(self) -> Dict:
        """Récupère les statistiques globales."""
        logger.info("[OPNsense] Consultation statistiques")

        if self._api_client:
            try:
                return await self._api_client.get_firewall_statistics()
            except Exception as e:
                logger.error(f"Erreur consultation stats: {e}")
                return {"status": "error", "message": str(e)}

        return {"packets": 1234567, "bytes": 9876543210, "mode": "simulation"}

    async def _get_rule_statistics(self) -> Dict:
        """Récupère les statistiques par règle."""
        logger.info("[OPNsense] Checking rule stats")

        if self._api_client:
            try:
                return await self._api_client.get_rule_statistics()
            except Exception as e:
                logger.error(f"Rule stats check error: {e}")
                return {"status": "error", "message": str(e)}

        return {"rules": [], "mode": "simulation"}

    # --- Active Diagnostics ---

    async def _ping_host(self, host: str, count: int = 3) -> Dict:
        """Ping une adresse IP ou un domaine."""
        logger.info(f"[OPNsense] Ping: {host}")
        if self._api_client:
            try:
                res = await self._api_client.ping_host(host, count)
                # Note: OPNsense returns a job ID to poll if async, but often the set cmd triggers it. 
                # For this agent simplification, returning the API acknowledgment is enough to show action.
                return res
            except Exception as e:
                return {"status": "error", "message": str(e)}
        return {"status": "success", "output": f"64 bytes from {host}: icmp_seq=1 ttl=64 time=1.23 ms", "mode": "simulation"}

    async def _traceroute_host(self, host: str) -> Dict:
        """Trace la route vers une adresse IP ou domaine."""
        logger.info(f"[OPNsense] Traceroute: {host}")
        if self._api_client:
            try:
                return await self._api_client.traceroute_host(host)
            except Exception as e:
                return {"status": "error", "message": str(e)}
        return {"status": "success", "output": f"1  192.168.1.1  1.000 ms\n2  {host}  10.000 ms", "mode": "simulation"}

    async def _port_probe(self, host: str, port: int) -> Dict:
        """Teste l'ouverture d'un port TCP sur une cible."""
        logger.info(f"[OPNsense] Port Probe: {host}:{port}")
        if self._api_client:
            try:
                return await self._api_client.port_probe(host, port)
            except Exception as e:
                return {"status": "error", "message": str(e)}
        return {"status": "success", "output": f"Port {port} is OPEN on {host}", "mode": "simulation"}
