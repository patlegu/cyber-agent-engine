# SPDX-License-Identifier: AGPL-3.0-or-later

import ipaddress
import json
import logging
import re
import subprocess
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

class CrowdSecAPIError(Exception):
    """Exception raised for CrowdSec API errors."""
    pass

class CrowdSecClient:
    """
    Client for CrowdSec Local API (LAPI).
    
    Interacts with the CrowdSec Local API to manage decisions and alerts.
    Default URL: http://localhost:8080/v1
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8080/v1",
        verify_ssl: bool = False,
        timeout: int = 10,
        cscli_path: str = "cscli",
    ):
        """
        Initialize the CrowdSec API client.
        
        Args:
            api_key: The CrowdSec API Key (Bouncer key).
            base_url: The base URL of the LAPI.
            verify_ssl: Whether to verify SSL certificates.
            timeout: Request timeout in seconds.
            cscli_path: Path to the cscli binary (default: "cscli" from PATH).
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.cscli_path = cscli_path
        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": self.api_key,
            "User-Agent": "OPNsense-Agent/1.0"
        })
        self.session.verify = verify_ssl

        logger.info(f"CrowdSec Client initialized: {self.base_url}")

    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, json_data: Optional[Dict] = None) -> Dict:
        """Internal method to handle requests."""
        url = urljoin(self.base_url + '/', endpoint.lstrip('/'))
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                timeout=self.timeout
            )
            response.raise_for_status()
            # Handle 204 No Content or empty responses
            if response.status_code == 204 or not response.content:
                return {}
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Error: {e}")
            raise CrowdSecAPIError(f"HTTP {e.response.status_code}: {e.response.text}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Request Error: {e}")
            raise CrowdSecAPIError(f"Request failed: {str(e)}")

    # ------------------------------------------------------------------
    # Input validators  (strategy 4 — structural validation)
    # ------------------------------------------------------------------

    # Go duration: one or more <digits><unit> segments, units: ns us ms s m h d
    _GO_DURATION_RE = re.compile(r'^(\d+(ns|us|µs|ms|[smhd]))+$')
    # ISO-3166-1 alpha-2 country code: exactly 2 uppercase letters
    _COUNTRY_CODE_RE = re.compile(r'^[A-Z]{2}$')

    @staticmethod
    def _validate_ip(addr: str) -> None:
        """Raise CrowdSecAPIError if addr is not a valid IP address."""
        try:
            ipaddress.ip_address(addr)
        except ValueError:
            raise CrowdSecAPIError(f"Invalid IP address: {addr!r}")

    @staticmethod
    def _validate_cidr(cidr: str) -> None:
        """Raise CrowdSecAPIError if cidr is not a valid CIDR range."""
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            raise CrowdSecAPIError(f"Invalid CIDR range: {cidr!r}")

    @classmethod
    def _validate_ip_or_cidr(cls, value: str) -> None:
        """Raise CrowdSecAPIError if value is neither a valid IP nor a CIDR."""
        try:
            ipaddress.ip_address(value)
            return
        except ValueError:
            pass
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError:
            raise CrowdSecAPIError(f"Invalid IP or CIDR: {value!r}")

    @classmethod
    def _validate_duration(cls, duration: str) -> None:
        """Raise CrowdSecAPIError if duration is not a valid Go duration string."""
        if not cls._GO_DURATION_RE.match(duration):
            raise CrowdSecAPIError(
                f"Invalid duration: {duration!r}. Expected Go duration (ex: '4h', '24h', '30m', '168h')."
            )

    @classmethod
    def _validate_decision_value(cls, value: str, scope: str) -> None:
        """Validate value according to its scope (ip / range / country)."""
        if scope == "ip":
            cls._validate_ip(value)
        elif scope == "range":
            cls._validate_cidr(value)
        elif scope == "country":
            if not cls._COUNTRY_CODE_RE.match(value):
                raise CrowdSecAPIError(f"Invalid country code: {value!r}. Expected ISO-3166-1 alpha-2 (ex: 'CN', 'RU').")
        # unknown scope: let the LAPI reject it

    def get_decisions(
        self,
        ip: Optional[str] = None,
        scope: Optional[str] = None,
        value: Optional[str] = None,
        type: Optional[str] = None,
        range: Optional[str] = None,
        origins: Optional[str] = None,
        scenarios_containing: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Get active decisions. All filters are optional and combinable."""
        if ip:    self._validate_ip(ip)
        if range: self._validate_cidr(range)
        params: Dict = {"limit": limit}
        if ip:                     params["ip"] = ip
        if scope:                  params["scope"] = scope
        if value:                  params["value"] = value
        if type:                   params["type"] = type
        if range:                  params["range"] = range
        if origins:                params["origins"] = origins
        if scenarios_containing:   params["scenarios_containing"] = scenarios_containing
        return self._request("GET", "decisions", params=params) or []

    def add_decision(
        self,
        value: str,
        scope: str = "ip",
        type: str = "ban",
        duration: str = "4h",
        reason: str = "manual",
    ) -> Dict:
        """Add a decision (ban, captcha, …)."""
        self._validate_decision_value(value, scope)
        self._validate_duration(duration)
        data = {
            "value": value,
            "scope": scope,
            "type": type,
            "duration": duration,
            "scenario": reason,
            "origin": "cscli",
        }
        return self._request("POST", "decisions", json_data=data)

    def delete_decision(self, decision_id: int) -> Dict:
        """Delete a decision by ID."""
        return self._request("DELETE", f"decisions/{decision_id}")

    def delete_decision_by_ip(self, ip: str) -> Dict:
        """Delete all decisions for a specific IP."""
        self._validate_ip(ip)
        return self._request("DELETE", "decisions", params={"value": ip, "scope": "ip"})

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def get_alerts(
        self,
        limit: int = 100,
        ip: Optional[str] = None,
        range: Optional[str] = None,
        scenario: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        has_active_decision: Optional[bool] = None,
        decision_type: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> List[Dict]:
        """Search alerts with optional filters."""
        if ip:    self._validate_ip(ip)
        if range: self._validate_cidr(range)
        params: Dict = {"limit": limit}
        if ip:                              params["ip"] = ip
        if range:                           params["range"] = range
        if scenario:                        params["scenario"] = scenario
        if since:                           params["since"] = since
        if until:                           params["until"] = until
        if has_active_decision is not None: params["has_active_decision"] = str(has_active_decision).lower()
        if decision_type:                   params["decision_type"] = decision_type
        if origin:                          params["origin"] = origin
        return self._request("GET", "alerts", params=params) or []

    def get_alert(self, alert_id: int) -> Dict:
        """Get a single alert by its numeric ID."""
        return self._request("GET", f"alerts/{alert_id}")

    def delete_alert(self, alert_id: int) -> Dict:
        """Delete a specific alert by its numeric ID."""
        return self._request("DELETE", f"alerts/{alert_id}")

    # ------------------------------------------------------------------
    # Allowlists
    # ------------------------------------------------------------------

    def get_allowlists(self) -> List[Dict]:
        """List all configured allowlists (whitelists)."""
        return self._request("GET", "allowlists") or []

    def check_allowlist(self, ip_or_range: str) -> Dict:
        """Check whether an IP or CIDR range appears in any allowlist."""
        self._validate_ip_or_cidr(ip_or_range)  # prevents path traversal in URL
        return self._request("GET", f"allowlists/check/{ip_or_range}")

    # ------------------------------------------------------------------
    # cscli — local CLI (bouncers, machines, metrics, hub, simulation)
    # ------------------------------------------------------------------

    # Subcommands that _run_cscli is allowed to execute (allowlist).
    _CSCLI_ALLOWED_SUBCOMMANDS: frozenset = frozenset({
        ("bouncers", "list"),
        ("machines", "list"),
        ("metrics",),
        ("hub", "upgrade"),
        ("simulation", "enable"),
        ("simulation", "disable"),
    })

    # Valid scenario name: letters, digits, dash, underscore, dot, slash only.
    # Matches patterns like "crowdsecurity/ssh-bf" or "myorg/custom_rule.1".
    import re as _re
    _SCENARIO_RE = _re.compile(r'^[a-zA-Z0-9_.\-/]+$')

    def _run_cscli(self, *args: str, parse_json: bool = True) -> Any:
        """Run an allowlisted cscli command and return parsed output.

        Security:
        - ``shell=False`` (implicit with list): no shell metacharacter interpretation.
        - Subcommand prefix validated against ``_CSCLI_ALLOWED_SUBCOMMANDS``.
        - ``cscli_path`` must be an absolute path or the bare name ``cscli``.
        - Raises CrowdSecAPIError on non-zero exit, timeout, or JSON error.
        """
        # Validate cscli_path: must be "cscli" or an absolute path with no spaces/shell chars.
        if self.cscli_path != "cscli":
            import os
            if not os.path.isabs(self.cscli_path) or not self.cscli_path.replace("_", "").replace("-", "").replace("/", "").replace(".", "").isalnum():
                raise CrowdSecAPIError(f"Invalid cscli_path: {self.cscli_path!r}")

        # Validate that the subcommand prefix is in the allowlist.
        # We check the first 1 or 2 tokens (e.g. ("hub", "upgrade") or ("metrics",)).
        prefix2 = tuple(args[:2]) if len(args) >= 2 else None
        prefix1 = (args[0],) if args else None
        if prefix2 not in self._CSCLI_ALLOWED_SUBCOMMANDS and prefix1 not in self._CSCLI_ALLOWED_SUBCOMMANDS:
            raise CrowdSecAPIError(f"Subcommand not allowed: {' '.join(args)}")

        cmd = [self.cscli_path] + list(args)
        if parse_json:
            cmd += ["-o", "json"]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                msg = result.stderr.strip() or result.stdout.strip()
                raise CrowdSecAPIError(f"cscli error ({' '.join(args)}): {msg}")
            if not parse_json:
                return result.stdout.strip()
            output = result.stdout.strip()
            return json.loads(output) if output else {}
        except subprocess.TimeoutExpired:
            raise CrowdSecAPIError(f"cscli command timed out: {' '.join(args)}")
        except json.JSONDecodeError as e:
            raise CrowdSecAPIError(f"cscli JSON parse error: {e}")
        except FileNotFoundError:
            raise CrowdSecAPIError(f"cscli not found at: {self.cscli_path}")

    def list_bouncers(self) -> List[Dict]:
        """List registered bouncers (remediation components)."""
        result = self._run_cscli("bouncers", "list")
        return result if isinstance(result, list) else []

    def list_machines(self) -> List[Dict]:
        """List registered machines (log processors / agents)."""
        result = self._run_cscli("machines", "list")
        return result if isinstance(result, list) else []

    def get_metrics(self) -> Dict:
        """Get CrowdSec metrics (parsers, scenarios, bouncers activity)."""
        return self._run_cscli("metrics") or {}

    def hub_upgrade(self, force: bool = False) -> Dict:
        """Upgrade CrowdSec hub items (parsers, scenarios, postoverflows).

        Args:
            force: Pass --force to re-download even up-to-date items.
        """
        args = ["hub", "upgrade"]
        if force:
            args.append("--force")
        output = self._run_cscli(*args, parse_json=False)
        return {"output": output}

    def set_simulation(self, action: str, scenario: Optional[str] = None) -> Dict:
        """Enable or disable simulation mode.

        Args:
            action: "enable" or "disable".
            scenario: Scenario name (ex: "crowdsecurity/ssh-bf").
                      Omit to apply globally.
        """
        if action not in ("enable", "disable"):
            raise CrowdSecAPIError(f"Invalid simulation action: {action!r}. Must be 'enable' or 'disable'.")
        if scenario is not None and not self._SCENARIO_RE.match(scenario):
            raise CrowdSecAPIError(f"Invalid scenario name: {scenario!r}. Only alphanumeric, dash, underscore, dot and slash allowed.")
        args = ["simulation", action]
        if scenario:
            args.append(scenario)
        output = self._run_cscli(*args, parse_json=False)
        return {"action": action, "scenario": scenario or "global", "output": output}
