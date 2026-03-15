"""
coordinator/judge.py — CAPValidator : validation d'un paquet CAP v1 avant exécution.

Deux niveaux de validation :
  1. Schéma (déterministe, sans LLM) :
     - La directive existe-t-elle dans les capacités de l'agent cible ?
     - Les arguments obligatoires sont-ils présents (entities + args) ?
     - Les valeurs enum sont-elles dans la liste autorisée ?
  2. Sémantique (LLM léger, optionnel) — prévu Phase 1.2, non implémenté ici.

Usage dans pilot.py :
    verdict = self._judge.validate(cap, agent_name, self._capabilities)
    if not verdict.passed:
        # traiter comme FAILED avec raison structurée
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .models import CoordinatorDirective

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Résultat de validation
# ---------------------------------------------------------------------------

@dataclass
class JudgeVerdict:
    """Résultat de la validation d'un paquet CAP v1."""
    passed: bool
    reason: str = ""
    # Champs manquants identifiés (pour aider la reformulation)
    missing_args: list[str] = field(default_factory=list)
    # Valeurs enum invalides : {arg: valeur_fournie}
    invalid_enums: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls) -> "JudgeVerdict":
        return cls(passed=True)

    @classmethod
    def fail(
        cls,
        reason: str,
        missing_args: Optional[list[str]] = None,
        invalid_enums: Optional[dict[str, Any]] = None,
    ) -> "JudgeVerdict":
        return cls(
            passed=False,
            reason=reason,
            missing_args=missing_args or [],
            invalid_enums=invalid_enums or {},
        )

    def to_error_result(self) -> dict:
        """Convertit le verdict en dict résultat compatible avec le format TaskResult."""
        detail: dict[str, Any] = {"success": False, "error": f"JudgeAgent: {self.reason}"}
        if self.missing_args:
            detail["missing_args"] = self.missing_args
        if self.invalid_enums:
            detail["invalid_enums"] = self.invalid_enums
        return detail


# ---------------------------------------------------------------------------
# Validator principal
# ---------------------------------------------------------------------------

class CAPValidator:
    """
    Valide un paquet CoordinatorDirective contre le schéma de capacités d'un agent.

    Le schéma attendu est le format retourné par GET /capabilities :
    {
        "agents": [
            {
                "name": "opnsense",
                "functions": [
                    {
                        "name": "block_ip",
                        "description": "...",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "ip": {"type": "string"},
                                "interface": {"type": "string", "enum": ["wan", "lan", "opt1"]}
                            },
                            "required": ["ip"]
                        }
                    },
                    ...
                ]
            }
        ]
    }
    """

    def __init__(self) -> None:
        # Index local : {agent_name: {directive: function_schema}}
        self._index: dict[str, dict[str, dict]] = {}

    # ------------------------------------------------------------------
    # Construction de l'index
    # ------------------------------------------------------------------

    def update(self, capabilities: dict) -> None:
        """
        Met à jour l'index interne à partir d'une réponse /capabilities.

        Appelé par PilotAgent dès que self._capabilities est mis à jour.
        """
        self._index = {}
        for agent in capabilities.get("agents", []):
            agent_name = agent.get("name", "")
            funcs = {fn["name"]: fn for fn in agent.get("functions", []) if "name" in fn}
            # Inclure aussi les aliases
            for fn in agent.get("functions", []):
                for alias in fn.get("aliases", []):
                    funcs[alias] = fn
            self._index[agent_name] = funcs
        logger.debug(
            "CAPValidator index mis à jour : %d agents, %d fonctions au total",
            len(self._index),
            sum(len(fns) for fns in self._index.values()),
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(
        self,
        cap: CoordinatorDirective,
        agent_name: str,
    ) -> JudgeVerdict:
        """
        Valide un paquet CAP v1 pour un agent donné.

        Args:
            cap:        Paquet CoordinatorDirective à valider.
            agent_name: Nom de l'agent cible (ex: "opnsense").

        Returns:
            JudgeVerdict.ok() si valide, JudgeVerdict.fail(...) sinon.
        """
        # Index vide → pas de validation possible (dégradation gracieuse)
        if not self._index:
            logger.debug("CAPValidator: index vide, validation ignorée")
            return JudgeVerdict.ok()

        agent_funcs = self._index.get(agent_name)
        if agent_funcs is None:
            # Agent inconnu dans l'index — on laisse passer (peut être un agent non encore indexé)
            logger.debug("CAPValidator: agent '%s' non indexé, validation ignorée", agent_name)
            return JudgeVerdict.ok()

        # 1. La directive existe-t-elle ?
        fn_schema = agent_funcs.get(cap.directive)
        if fn_schema is None:
            known = sorted(agent_funcs.keys())[:10]
            return JudgeVerdict.fail(
                reason=(
                    f"directive '{cap.directive}' inconnue pour l'agent '{agent_name}'. "
                    f"Exemples valides : {', '.join(known)}{'…' if len(agent_funcs) > 10 else ''}"
                ),
            )

        # 2. Arguments obligatoires présents ?
        params = fn_schema.get("parameters", {})
        required = params.get("required", [])
        props = params.get("properties", {})

        # Valeurs disponibles = entities (premier élément de chaque type) + args
        available = cap.all_params()

        missing = []
        for arg in required:
            val = available.get(arg)
            if val is None or val == "" or val == []:
                missing.append(arg)

        if missing:
            return JudgeVerdict.fail(
                reason=f"arguments obligatoires manquants : {', '.join(missing)}",
                missing_args=missing,
            )

        # 3. Valeurs enum valides ?
        invalid_enums: dict[str, Any] = {}
        for arg, val in available.items():
            prop = props.get(arg, {})
            allowed = prop.get("enum")
            if allowed and val not in allowed:
                invalid_enums[arg] = val

        if invalid_enums:
            details = ", ".join(
                f"{k}={v!r} (attendu: {props[k].get('enum')})"
                for k, v in invalid_enums.items()
                if k in props
            )
            return JudgeVerdict.fail(
                reason=f"valeurs enum invalides : {details}",
                invalid_enums=invalid_enums,
            )

        return JudgeVerdict.ok()
