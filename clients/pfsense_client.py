# SPDX-License-Identifier: AGPL-3.0-or-later
import logging
import httpx
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class PfSenseClient:
    """Client API pour pfSense (via pfSense-pkg-RESTAPI)."""
    
    def __init__(self, base_url: str, api_key: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip('/')
        self.headers = {
            "Authorization": api_key,
            "Content-Type": "application/json"
        }
        self.verify_ssl = verify_ssl
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            verify=verify_ssl
        )

    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
        try:
            response = await self.client.request(
                method, endpoint, json=data
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"pfSense API Error ({endpoint}): {e}")
            return {"status": "error", "message": str(e)}

    async def add_alias(self, alias_data: Dict) -> Dict:
        """
        Adaptateur OPNsense -> pfSense.
        OPNsense: {'alias': {'name': '...', 'description': '...'}}
        pfSense: {'name': '...', 'descr': '...'}
        """
        data = alias_data.get('alias', alias_data)
        pfsense_data = {
            "name": data.get('name'),
            "descr": data.get('description', ''),
            "type": data.get('type', 'host'),
            "address": data.get('content', '').split('\n')
        }
        return await self._request("POST", "/api/v2/firewall/alias", pfsense_data)

    async def get_system_stats(self) -> Dict:
        return await self._request("GET", "/api/v2/system/status")
