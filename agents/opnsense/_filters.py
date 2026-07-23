# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Règles de filtrage firewall — 6 méthodes.
"""

import logging
from typing import Dict, Literal, Optional

from ._decorators import safety_snapshot

logger = logging.getLogger(__name__)


def _selected_value(field) -> str:
    """Extrait la clé sélectionnée d'un champ OPNsense {key: {value, selected}}."""
    if not isinstance(field, dict):
        return str(field) if field else ""
    selected = [k for k, v in field.items() if isinstance(v, dict) and v.get("selected") == 1]
    return selected[0] if selected else ""


def _normalize_filter_rules(raw: dict, single_uuid: Optional[str] = None) -> dict:
    """Transforme la réponse API OPNsense brute en liste de règles lisibles.

    Chaque règle retournée contient :
      uuid, description, action, interface, protocol, direction,
      source, destination, destination_port, enabled
    """
    rules_raw = raw.get("filter", {}).get("rules", {}).get("rule", {})

    if not rules_raw:
        # Réponse pour une règle unique (GET /filter/getRule/{uuid})
        rules_raw = raw.get("rule", {})
        if rules_raw and single_uuid:
            rules_raw = {single_uuid: rules_raw}

    normalized = []
    for rule_uuid, rule in rules_raw.items():
        normalized.append({
            "uuid":             rule_uuid,
            "description":      rule.get("description", ""),
            "enabled":          rule.get("enabled", "0") == "1",
            "action":           _selected_value(rule.get("action", {})),
            "interface":        _selected_value(rule.get("interface", {})),
            "direction":        _selected_value(rule.get("direction", {})),
            "protocol":         _selected_value(rule.get("protocol", {})) or "any",
            "source":           rule.get("source_net", "any") or "any",
            "source_port":      rule.get("source_port", "") or "",
            "destination":      rule.get("destination_net", "any") or "any",
            "destination_port": rule.get("destination_port", "") or "",
        })

    # Tri par sequence pour respecter l'ordre d'évaluation du firewall
    try:
        normalized.sort(key=lambda r: int(
            rules_raw.get(r["uuid"], {}).get("sequence", 9999)
        ))
    except (ValueError, TypeError):
        pass

    return {"total": len(normalized), "rules": normalized}


class FilterRulesMixin:

    @safety_snapshot
    async def _create_filter_rule(
        self,
        interface: Literal["wan", "lan", "opt1", "opt2"],
        description: str = "Created by Agent",
        protocol: Literal["any", "tcp", "udp", "icmp"] = "any",
        action: Literal["block", "pass"] = "block",
        **kwargs
    ) -> Dict:
        """Crée une règle de filtrage firewall sur une interface réseau.

        :param interface: Interface réseau cible. 'wan' pour le trafic Internet entrant,
            'lan' pour le réseau local, 'opt1'/'opt2' pour les interfaces optionnelles.
        :param description: Description lisible de la règle.
        :param protocol: Protocole concerné : 'any' (tous), 'tcp', 'udp' ou 'icmp'.
        :param action: Action à appliquer : 'block' pour bloquer, 'pass' pour autoriser.
            Par défaut : 'block'. NE PAS utiliser 'allow', 'deny' ou 'drop'.
        """
        logger.info(f"[OPNsense] Creating rule: {description} | interface={interface} | action={action}")

        if self._api_client:
            try:
                action_lower = action.lower()
                if action_lower in ["drop", "deny"]:
                    action = "block"
                elif action_lower in ["accept", "allow"]:
                    action = "pass"

                proto_map = {"tcp": "TCP", "udp": "UDP", "icmp": "ICMP", "any": "any"}
                protocol = proto_map.get(protocol.lower(), protocol)

                rule_data = {
                    "rule": {
                        "description": description,
                        "interface": interface,
                        "protocol": protocol,
                        "type": action,
                        "enabled": "1",
                        **{k: v for k, v in kwargs.items() if v is not None}
                    }
                }

                response = await self._api_client.add_filter_rule(rule_data)

                if response.get('result') == 'saved':
                    await self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Rule '{description}' created and applied")

                return response

            except Exception as e:
                logger.error(f"Rule creation error: {e}")
                return {"status": "error", "message": str(e)}

        return {
            "status": "created",
            "uuid": f"rule-{hash(description) % 10000}",
            "description": description,
            "mode": "simulation"
        }

    @safety_snapshot
    async def _delete_filter_rule(self, uuid: str) -> Dict:
        """Supprime une règle de filtrage."""
        logger.info(f"[OPNsense] Removing rule: {uuid}")

        if self._api_client:
            try:
                response = await self._api_client.delete_filter_rule(uuid)
                if response.get('result') == 'deleted':
                    await self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Rule {uuid} removed and applied")
                return response
            except Exception as e:
                logger.error(f"Rule removal error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "deleted", "uuid": uuid, "mode": "simulation"}

    @safety_snapshot
    async def _update_filter_rule(self, uuid: str, **kwargs) -> Dict:
        """Modifie une règle de filtrage existante."""
        logger.info(f"[OPNsense] Modifying rule: {uuid}")

        if self._api_client:
            try:
                rule_data = {"rule": {k: v for k, v in kwargs.items() if v is not None}}
                response = await self._api_client.update_filter_rule(uuid, rule_data)
                if response.get('result') == 'saved':
                    await self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Rule {uuid} modified and applied")
                return response
            except Exception as e:
                logger.error(f"Rule modification error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "updated", "uuid": uuid, "mode": "simulation"}

    @safety_snapshot
    async def _toggle_filter_rule(self, uuid: str, enabled: bool) -> Dict:
        """Active ou désactive une règle."""
        logger.info(f"[OPNsense] Toggle rule {uuid}: {'enabled' if enabled else 'disabled'}")

        if self._api_client:
            try:
                response = await self._api_client.toggle_filter_rule(uuid, enabled)
                if response.get('result') == 'saved':
                    await self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Rule {uuid} {'enabled' if enabled else 'disabled'}")
                return response
            except Exception as e:
                logger.error(f"Rule toggle error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "toggled", "uuid": uuid, "enabled": enabled, "mode": "simulation"}

    @safety_snapshot
    async def _move_filter_rule(self, uuid: str, before_uuid: str, **kwargs) -> Dict:
        """Déplace une règle avant une autre."""
        logger.info(f"[OPNsense] Moving rule {uuid} before {before_uuid}")

        if self._api_client:
            try:
                response = await self._api_client.move_filter_rule(uuid, before_uuid)
                if response.get('result') == 'saved':
                    await self._api_client.apply_firewall_changes()
                    logger.info(f"✓ Rule {uuid} moved")
                return response
            except Exception as e:
                logger.error(f"Rule move error: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "moved", "uuid": uuid, "mode": "simulation"}

    async def _get_filter_rule(self, uuid: Optional[str] = None) -> Dict:
        """Récupère et normalise une ou toutes les règles de filtrage firewall.

        Retourne une liste plate de règles avec les champs essentiels :
        uuid, description, action, interface, protocol, direction,
        source, destination, destination_port, enabled.
        """
        logger.info(f"[OPNsense] Checking rules{f': {uuid}' if uuid else ''}")

        if self._api_client:
            try:
                raw = await self._api_client.get_filter_rule(uuid)
                return _normalize_filter_rules(raw, uuid)
            except Exception as e:
                logger.error(f"Rule check error: {e}")
                return {"status": "error", "message": str(e)}

        return {"total": 0, "rules": [], "mode": "simulation"}
