# SPDX-License-Identifier: AGPL-3.0-or-later
import logging
import asyncio
import json
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class LinuxSysClient:
    """Client pour la gestion système Linux standalone (Polyfill OPNsense)."""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}

    async def _run_command(self, cmd: List[str]) -> str:
        """Exécute une commande système de manière asynchrone."""
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode().strip()
            logger.error(f"Command failed: {' '.join(cmd)} - Error: {error_msg}")
            raise RuntimeError(error_msg)
            
        return stdout.decode().strip()

    async def get_system_health(self) -> Dict:
        """Simule le statut système OPNsense à partir de commandes Linux."""
        try:
            # CPU Load
            uptime_out = await self._run_command(["uptime"])
            load = uptime_out.split("load average:")[1].strip()
            
            # Memory
            free_out = await self._run_command(["free", "-m"])
            mem = free_out.split("\n")[1].split()
            mem_total = int(mem[1])
            mem_used = int(mem[2])
            
            return {
                "system": {
                    "load": load,
                    "memory": f"{mem_used}MB / {mem_total}MB",
                    "platform": "linux",
                    "status": "Healthy"
                }
            }
        except Exception as e:
            logger.error(f"Linux health error: {e}")
            return {"status": "error", "message": str(e)}

    async def crowdsec_block(self, ip: str, reason: str = "Blocked by Agent") -> Dict:
        """Bloque une IP via CrowdSec."""
        try:
            cmd = ["cscli", "decisions", "add", "--ip", ip, "--reason", reason]
            await self._run_command(cmd)
            return {"status": "success", "ip": ip, "action": "blocked", "provider": "crowdsec"}
        except Exception as e:
            logger.error(f"CrowdSec error: {e}")
            return {"status": "error", "message": str(e)}

    async def crowdsec_unblock(self, ip: str) -> Dict:
        """Débloque une IP via CrowdSec."""
        try:
            cmd = ["cscli", "decisions", "delete", "--ip", ip]
            await self._run_command(cmd)
            return {"status": "success", "ip": ip, "action": "unblocked", "provider": "crowdsec"}
        except Exception as e:
            logger.error(f"CrowdSec delete error: {e}")
            return {"status": "error", "message": str(e)}
