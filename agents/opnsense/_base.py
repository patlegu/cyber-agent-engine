# SPDX-License-Identifier: AGPL-3.0-or-later
"""
agents/opnsense/_base.py

OPNsenseAgent — agent-outil pour firewall OPNsense/pfSense.
Exposé sous le nom d'outil "opnsense" dans l'API HTTP (/capabilities, /agent/execute).

La classe est assemblée par héritage multiple (mixins). Chaque mixin gère
un domaine fonctionnel indépendant et expose ses propres fonctions via
son propre `_register_functions()`. Python MRO les chaîne automatiquement.

---

## Architecture — Mixins

| Fichier           | Domaine                        | Fonctions |
|-------------------|-------------------------------|----------:|
| _legacy.py        | Compat. block/unblock IP       |         2 |
| _filters.py       | Règles de filtrage firewall    |         6 |
| _aliases.py       | Alias IP/réseau/port           |        10 |
| _nat.py           | NAT et port forwarding         |         5 |
| _diagnostics.py   | Ping, traceroute, logs         |         7 |
| _config.py        | Backup, restore, apply         |         9 |
| _extended.py      | GeoIP, firmware, DNS, DHCP, ACME |      22 |
| _ids.py           | IDS/Suricata (règles, service) |         9 |
| _traffic.py       | Traffic shaping QoS/dummynet   |        11 |
| _vpn.py           | IPsec et OpenVPN               |        10 |
| _routing.py       | Routes statiques               |         3 |
| _monit.py         | Monit (monitoring services)    |         2 |
| _cron.py          | Tâches planifiées              |         3 |

---

## Ajouter une fonction dans un mixin existant

1. Choisir le fichier mixin dont le domaine correspond.

2. Définir la méthode :

       @safety_snapshot          # OBLIGATOIRE si l'action modifie ou supprime une ressource
       async def ma_fonction(self, param: str, action: Literal["add", "delete"] = "add") -> Dict:
           \"\"\"Résumé une ligne (extrait comme `description` dans get_capabilities()).

           :param param: Description affichée dans le schéma JSON exposé au LLM.
           :param action: Action à réaliser.
           \"\"\"

   Conventions :
   - `@safety_snapshot` → crée un point de restauration avant toute opération destructive.
   - `:param name:` obligatoire (format `_parse_param_docs()`) — pas `Args:`.
   - `Literal["v1", "v2"]` sur le type → enum dans le schéma OpenAI function-calling.

3. Enregistrer dans `_register_functions()` du mixin :

       "ma_fonction": self.ma_fonction,

## Créer un nouveau mixin (nouveau domaine)

1. Créer `agents/opnsense/_mon_domaine.py` avec la classe `MonDomaineMixin`.
2. L'importer ici et l'ajouter à la liste d'héritage de `OPNsenseAgent`.

Seuil indicatif : justifié à partir de ~15 fonctions propres sur un domaine distinct.
En dessous, ajouter les méthodes dans le mixin existant le plus proche.

---

## Compatibilité pfSense

`self.platform` vaut `"opnsense"` ou `"pfsense"`. Certaines fonctions utilisent
des clés différentes selon la plateforme (ex: `"descr"` vs `"description"`).
Le client API gère ces différences — les méthodes de l'agent n'ont pas à en tenir compte.
"""

import logging
from typing import Dict, List, Optional, Any

from ..base import ToolAgent
from ._legacy import LegacyMixin
from ._filters import FilterRulesMixin
from ._aliases import AliasesMixin
from ._nat import NATMixin
from ._diagnostics import DiagnosticsMixin
from ._config import ConfigMixin
from ._extended import ExtendedMixin
from ._ids import IDSMixin
from ._monit import MonitMixin
from ._cron import CronMixin
from ._routing import RoutingMixin
from ._traffic import TrafficShaperMixin
from ._vpn import VPNMixin

logger = logging.getLogger(__name__)


class OPNsenseAgent(
    LegacyMixin,
    FilterRulesMixin,
    AliasesMixin,
    NATMixin,
    DiagnosticsMixin,
    ConfigMixin,
    ExtendedMixin,
    IDSMixin,
    MonitMixin,
    CronMixin,
    RoutingMixin,
    TrafficShaperMixin,
    VPNMixin,
    ToolAgent,
):
    """
    Agent-outil pour firewall OPNsense — Version complète.

    Fonctions supportées (50+ au total) réparties en 7 catégories.
    Supporte les plateformes : opnsense, pfsense, linux.
    """

    agent_role  = "OPNsense firewall agent"
    chat_format = "qwen"
    system_prompt = (
        "Tu es un agent OPNsense. Tu reçois des directives structurées du coordinateur "
        "sous forme de paquets JSON (format CAP v1 : directive + entities + args) et tu génères "
        "des appels d'API précis sous forme de tool_calls. "
        "Tu ne réponds jamais en langage naturel — uniquement des tool_calls."
    )

    def __init__(
        self,
        model_path: str,
        api_config: Optional[Dict] = None,
        ollama_config: Optional[Dict] = None,
        platform: str = "opnsense",
        vllm_client: Optional[Any] = None,
        openai_client: Optional[Any] = None,
        lora_model: str = "",
    ):
        # platform doit être défini AVANT super().__init__ car _register_functions
        # peut en avoir besoin via les Mixins lors de l'init de ToolAgent
        self.platform = platform.lower()
        self._api_client = None

        super().__init__(
            tool_name="opnsense",
            model_path=model_path,
            api_config=api_config,
            ollama_config=ollama_config,
            vllm_client=vllm_client,
            openai_client=openai_client,
            lora_model=lora_model,
        )

        # Initialisation du client API selon la plateforme
        if self.platform == "opnsense":
            if api_config and all(k in api_config for k in ['base_url', 'api_key', 'api_secret']):
                from clients import OPNsenseAPIClient
                self._api_client = OPNsenseAPIClient(
                    base_url=api_config['base_url'],
                    api_key=api_config['api_key'],
                    api_secret=api_config['api_secret'],
                    verify_ssl=api_config.get('verify_ssl', True),
                    timeout=api_config.get('timeout', 30),
                )
                logger.info("✓ Client API OPNsense initialisé")
            else:
                logger.debug("OPNsense: Initialisé sans API (mode locale/simulation)")

        elif self.platform == "pfsense":
            if api_config and all(k in api_config for k in ['base_url', 'api_key']):
                from clients.pfsense_client import PfSenseClient
                self._api_client = PfSenseClient(
                    base_url=api_config['base_url'],
                    api_key=api_config['api_key'],
                    verify_ssl=api_config.get('verify_ssl', True),
                )
                logger.info("✓ Client API pfSense initialisé (Polyfill)")
            else:
                logger.debug("pfSense: Initialisé sans API (mode locale/simulation)")

        elif self.platform == "linux":
            from clients.linux_sys_client import LinuxSysClient
            self._api_client = LinuxSysClient(config=api_config)
            logger.info("✓ Client Système Linux initialisé (Polyfill)")

    def _register_functions(self) -> Dict[str, callable]:
        """Enregistre toutes les fonctions OPNsense.

        Les clés correspondent aux noms des actions dans l'API OPNsense :
          add_*  → POST .../add_item  ou .../add_rule
          del_*  → POST .../del_item  ou .../del_rule
          set_*  → POST .../set_item  ou .../set_rule
          get_*  → GET  .../get       ou .../get_item
        Ref : https://docs.opnsense.org/development/api/core/firewall.html
        """
        return {
            # Legacy (compatibilité block/unblock direct)
            "block_ip": self._block_ip,
            "unblock_ip": self._unblock_ip,

            # Règles de filtrage — filter/
            "add_filter_rule": self._create_filter_rule,    # filter/add_rule
            "del_filter_rule": self._delete_filter_rule,    # filter/del_rule
            "set_filter_rule": self._update_filter_rule,    # filter/set_rule
            "get_filter_rule": self._get_filter_rule,       # filter/get_rule
            "toggle_filter_rule": self._toggle_filter_rule, # filter/toggle_rule
            "move_filter_rule": self._move_filter_rule,     # filter/move_rule_before

            # Alias — firewall/alias/
            "add_alias": self._create_alias,                # alias/add_item
            "del_alias": self._delete_alias,                # alias/del_item
            "set_alias": self._update_alias,                # alias/set_item
            "get_alias": self._get_alias,                   # alias/get
            "import_alias": self._import_alias,             # alias/import
            # alias_util/
            "add_to_alias": self._add_to_alias,             # alias_util/add/{alias}
            "del_from_alias": self._delete_from_alias,      # alias_util/delete/{alias}
            "flush_alias": self._flush_alias,               # alias_util/flush/{alias}
            "list_alias_content": self._list_alias_content, # alias_util/list/{alias}
            "find_alias_references": self._find_alias_references,  # alias_util/find_references

            # NAT — source_nat/ / d_nat/ / one_to_one/
            "add_nat_outbound": self._create_nat_outbound,      # source_nat/add_rule
            "del_nat_outbound": self._delete_nat_outbound,      # source_nat/del_rule
            "add_nat_port_forward": self._create_nat_port_forward,  # d_nat/add_rule
            "add_nat_one_to_one": self._create_nat_one_to_one,  # one_to_one/add_rule
            "del_nat_one_to_one": self._delete_nat_one_to_one,  # one_to_one/del_rule

            # Diagnostics & Logs
            "get_firewall_log": self._get_firewall_log,
            "get_firewall_states": self._get_firewall_states,
            "kill_firewall_states": self._kill_firewall_states,
            "flush_firewall_states": self._flush_firewall_states,
            "get_firewall_statistics": self._get_firewall_statistics,
            "get_rule_statistics": self._get_rule_statistics,
            "get_system_status": self._get_system_status,
            "ping_host": self._ping_host,
            "traceroute_host": self._traceroute_host,
            "port_probe": self._port_probe,

            # Gestion de configuration — filter_base/
            "apply_firewall_changes": self._apply_firewall_changes,    # filter_base/apply
            "cancel_firewall_rollback": self._cancel_firewall_rollback, # filter_base/cancel_rollback
            "revert_firewall_changes": self._revert_firewall_changes,  # filter_base/revert
            "create_firewall_savepoint": self._create_firewall_savepoint,  # filter_base/savepoint
            "get_interface_list": self._get_interface_list,             # filter/get_interface_list

            # Backup / Restore (config XML)
            "backup_configuration": self._backup_configuration,
            "list_restore_points": self._list_restore_points,
            "revert_to_restore_point": self._revert_to_restore_point,
            "create_restore_point": self._create_restore_point,

            # Organisation — category/
            "add_category": self._create_category,              # category/add_item
            "del_category": self._delete_category,              # category/del_item
            "list_categories": self._list_available_categories, # filter_base/list_categories
            "update_bogons": self._update_bogons,               # alias_util/update_bogons

            # GeoIP
            "list_geoip_countries": self._list_geoip_countries, # alias/list_countries
            "get_geoip_database": self._get_geoip_database,    # alias/get_geo_ip

            # Firmware & Updates
            "check_updates": self._check_updates,
            "get_upgrade_status": self._get_upgrade_status,
            "upgrade_firmware": self._upgrade_firmware,

            # Network Services (Unbound DNS / DHCP)
            "add_dns_override": self._add_dns_override,
            "list_dns_overrides": self._list_dns_overrides,
            "del_dns_override": self._delete_dns_override,
            "manage_dns_blocklist": self._manage_dns_blocklist,
            "search_dns_queries": self._search_dns_queries,
            "get_dhcp_leases": self._get_dhcp_leases,
            "add_static_mapping": self._add_static_mapping,

            # Intrusion Detection (Suricata / IDS)
            "get_ids_status": self.get_ids_status,
            "query_ids_alerts": self.query_ids_alerts,
            "toggle_ids_rule": self.toggle_ids_rule,

            # Service Monitoring & Self-Healing (Monit)
            "get_monit_status": self.get_monit_status,
            "restart_monit_service": self.restart_monit_service,

            # Automation & Scheduling (Cron)
            "schedule_cron_job": self.schedule_cron_job,
            "toggle_cron_job": self.toggle_cron_job,
            "get_cron_jobs": self.get_cron_jobs,

            # Static Routing
            "get_static_routes": self.get_static_routes,
            "add_static_route": self.add_static_route,
            "del_static_route": self.del_static_route,
            **self._register_functions_extra(),
        }

    def _register_functions_extra(self) -> Dict[str, callable]:
        """Fonctions supplémentaires — Lots 1-4 (IDS+, Traffic, ACME, VPN)."""
        return {
            # IDS complémentaire — Lot 1
            "list_ids_rulesets":    self._list_ids_rulesets,
            "toggle_ids_ruleset":   self._toggle_ids_ruleset,
            "update_ids_rules":     self._update_ids_rules,
            "start_ids":            self._start_ids,
            "stop_ids":             self._stop_ids,
            "restart_ids":          self._restart_ids,

            # Traffic Shaping — Lot 2
            "get_traffic_statistics": self._get_traffic_statistics,
            "list_traffic_pipes":     self._list_traffic_pipes,
            "add_traffic_pipe":       self._add_traffic_pipe,
            "del_traffic_pipe":       self._del_traffic_pipe,
            "list_traffic_queues":    self._list_traffic_queues,
            "add_traffic_queue":      self._add_traffic_queue,
            "del_traffic_queue":      self._del_traffic_queue,
            "list_traffic_rules":     self._list_traffic_rules,
            "add_traffic_rule":       self._add_traffic_rule,
            "del_traffic_rule":       self._del_traffic_rule,
            "apply_traffic_changes":  self._apply_traffic_changes,

            # ACME / Certificats Let's Encrypt — Lot 3
            "get_acme_status":          self._get_acme_status,
            "list_acme_certificates":   self._list_acme_certificates,
            "sign_acme_certificate":    self._sign_acme_certificate,
            "update_acme_certificate":  self._update_acme_certificate,
            "revoke_acme_certificate":  self._revoke_acme_certificate,
            "list_acme_accounts":       self._list_acme_accounts,

            # IPsec — Lot 4
            "get_ipsec_status":          self._get_ipsec_status,
            "list_ipsec_connections":    self._list_ipsec_connections,
            "toggle_ipsec_connection":   self._toggle_ipsec_connection,
            "list_ipsec_sessions":       self._list_ipsec_sessions,
            "connect_ipsec_session":     self._connect_ipsec_session,
            "disconnect_ipsec_session":  self._disconnect_ipsec_session,

            # OpenVPN — Lot 4
            "list_openvpn_instances":   self._list_openvpn_instances,
            "toggle_openvpn_instance":  self._toggle_openvpn_instance,
            "list_openvpn_sessions":    self._list_openvpn_sessions,
            "kill_openvpn_session":     self._kill_openvpn_session,
        }
