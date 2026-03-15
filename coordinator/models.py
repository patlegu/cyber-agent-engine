"""
coordinator/models.py — Modèles Pydantic du coordinateur.

Contient :
- CoordinatorDirective : paquet structuré CAP v1 transmis par le coordinateur
  aux agents spécialisés.

Protocole CAP v1 (Coordinator-Agent Packet)
-------------------------------------------
Le coordinateur ne transmet jamais de langage naturel aux agents SLM.
Il construit un paquet JSON structuré à partir de :
  1. L'intent identifié par le LLM coordinateur
  2. Les entités extraites par AnonyNER
  3. Les arguments non-entité déjà résolus (UUIDs, valeurs discrètes…)

Le SLM agent reçoit ce paquet comme messages[1].content et génère
exclusivement un tool_call — jamais de texte libre.

Voir : roadmaps/AGENT_ARCHITECTURE_PARADIGM.md §3
"""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Schéma des entités NER — types reconnus par AnonyNER
# ---------------------------------------------------------------------------

_EMPTY_ENTITIES: dict[str, list[str]] = {
    "IP_ADDRESS":      [],
    "IP_SUBNET":       [],
    "HOSTNAME":        [],
    "PORT_NUMBER":     [],
    "INTERFACE":       [],
    "MAC_ADDRESS":     [],
    "SERVICE_ACCOUNT": [],
    "CVE":             [],
    "HASH":            [],
    "FIREWALL_RULE":   [],
    "VPN_USER":        [],
    "SNMP_COMMUNITY":  [],
}


# ---------------------------------------------------------------------------
# CoordinatorDirective — paquet CAP v1
# ---------------------------------------------------------------------------

class CoordinatorDirective(BaseModel):
    """
    Paquet structuré transmis par le coordinateur à un agent spécialisé.

    Format CAP v1 (Coordinator-Agent Packet).

    Champs :
    --------
    directive : str
        Verbe d'action normalisé en snake_case. Doit correspondre au nom
        de fonction cible (ex: "block_ip", "add_alias", "del_static_route").
        Le coordinateur le choisit à partir du plan décomposé + /capabilities.

    entities : dict[str, list[str]]
        Entités extraites par AnonyNER depuis le message utilisateur.
        Clés = types NER du schéma standard (voir _EMPTY_ENTITIES).
        Toutes les clés sont présentes, même si la liste est vide.
        Si AnonyNER est activée en mode anonymisation, les valeurs peuvent
        être des tokens (<IP_1>, <HOST_2>) plutôt que des valeurs réelles.

    args : dict[str, Any]
        Paramètres API non-NER déjà résolus par le coordinateur.
        Exemples : {"action": "block", "protocol": "tcp", "uuid": "f9ed38a8-..."}
        Utilisé pour les valeurs discrètes (Literal), les UUIDs, les booléens,
        les entiers — tout ce qu'AnonyNER ne produit pas.
        Le SLM agent merge entities + args pour construire les arguments finaux.

    context : dict
        Métadonnées de traçabilité — non utilisées pour l'appel API.
        Exemples : source, reason, confidence, run_id, user_id.

    Exemple complet :
    -----------------
    {
        "directive": "add_filter_rule",
        "entities": {
            "IP_ADDRESS": ["192.168.1.100"],
            "INTERFACE":  ["wan"],
            ...
        },
        "args": {
            "action":   "block",
            "protocol": "tcp"
        },
        "context": {
            "source":     "user",
            "run_id":     "plan-abc-1234",
            "confidence": 0.97
        }
    }
    """

    directive: str = Field(
        description=(
            "Verbe d'action normalisé (snake_case), identique au nom de fonction cible. "
            "Exemples : 'block_ip', 'add_alias', 'del_static_route'."
        )
    )

    entities: dict[str, list[str]] = Field(
        default_factory=lambda: dict(_EMPTY_ENTITIES),
        description=(
            "Entités extraites par AnonyNER. "
            "Clés = types NER standard. Toutes les clés sont présentes même si vides."
        ),
    )

    args: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Paramètres API non-NER résolus par le coordinateur : "
            "valeurs discrètes (action, protocol), UUIDs, booléens, entiers. "
            "Fusionnés avec entities pour construire les arguments finaux."
        ),
    )

    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Métadonnées de traçabilité (source, reason, confidence, run_id).",
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def to_user_message(self) -> str:
        """
        Sérialise le paquet en string JSON pour injection dans messages[].content.

        Usage dans pilot.py :
            req = AgentExecuteRequest(command=directive.to_user_message())
        """
        return json.dumps(self.model_dump(), ensure_ascii=False)

    def get_entity(self, entity_type: str, index: int = 0) -> Optional[str]:
        """
        Retourne la valeur d'une entité par type et index, ou None si absente.

        Exemple :
            directive.get_entity("IP_ADDRESS")    → "10.0.0.1"
            directive.get_entity("INTERFACE", 1)  → "lan" (deuxième interface)
        """
        values = self.entities.get(entity_type, [])
        return values[index] if index < len(values) else None

    def all_params(self) -> dict[str, Any]:
        """
        Fusionne entities (premier élément de chaque type) et args.

        Utilisé par le coordinateur pour vérifier la complétude avant envoi,
        et par les tests pour inspecter les paramètres résolus.
        """
        params: dict[str, Any] = {}
        for etype, values in self.entities.items():
            if values:
                params[etype] = values[0]
        params.update(self.args)
        return params

    @classmethod
    def from_anonyner(
        cls,
        directive: str,
        ner_result: dict[str, list[str]],
        args: Optional[dict[str, Any]] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> "CoordinatorDirective":
        """
        Construit un CoordinatorDirective à partir du résultat brut d'AnonyNER.

        Args:
            directive:   Nom de fonction cible (ex: "block_ip").
            ner_result:  Dict retourné par AnonyAgent.extract_entities().
            args:        Paramètres non-NER optionnels.
            context:     Métadonnées optionnelles.

        Returns:
            CoordinatorDirective prêt à sérialiser.
        """
        # Fusionner avec le schéma complet (toutes les clés présentes)
        entities = dict(_EMPTY_ENTITIES)
        entities.update({k: v for k, v in ner_result.items() if k in entities})

        return cls(
            directive=directive,
            entities=entities,
            args=args or {},
            context=context or {},
        )
