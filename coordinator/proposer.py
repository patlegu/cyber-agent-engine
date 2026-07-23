# SPDX-License-Identifier: AGPL-3.0-or-later
"""Proposer — adapte un LLM brut en producteur d'intentions validées.

Le LLM ne DÉCIDE rien : il PROPOSE. Sa sortie JSON est parsée, validée contre le
catalogue, et convertie en `core.Intention` (args = jetons). Une sortie invalide
déclenche un nouvel essai borné, l'erreur étant réinjectée pour guider le LLM.
"""

from __future__ import annotations

import json
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError

from core.policy.catalog import CapabilityCatalog, MissingArgs, UnknownCapability
from core.policy.models import Intention


class Act(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    intention: Intention


class Finish(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    summary: str


Proposal = Act | Finish


@runtime_checkable
class ChatLLM(Protocol):
    async def chat(self, messages: list[dict[str, str]], max_tokens: int = 1024) -> str: ...


class ProposerError(Exception):
    """Le LLM n'a pas produit de proposition valide dans le budget d'essais."""


_SYSTEM = (
    "Tu es un proposeur d'actions de sécurité réseau. Tu ne vois que des JETONS "
    "(IP_1, VPN_USER_2) — jamais de valeurs réelles ; recopie-les tels quels. "
    "À chaque tour, réponds STRICTEMENT en JSON, soit une action :\n"
    '  {{"action": {{"capability": "<nom>", "args": {{"<arg>": "<jeton|valeur>"}}}}}}\n'
    "soit la fin du plan :\n"
    '  {{"final": "<résumé>"}}\n'
    "Capacités autorisées : {capabilities}. Aucun texte hors du JSON."
)


class LlmProposer:
    """Adapte un `ChatLLM` en producteur de `Proposal` validées contre le catalogue."""

    def __init__(self, *, llm: ChatLLM, catalog: CapabilityCatalog, max_retries: int = 2) -> None:
        self._llm = llm
        self._catalog = catalog
        self._max_retries = max_retries

    def _system_message(self) -> dict[str, str]:
        caps = ", ".join(self._catalog.names())
        return {"role": "system", "content": _SYSTEM.format(capabilities=caps)}

    def _base_messages(self, request_tokens: str, history: list[str]) -> list[dict[str, str]]:
        msgs = [self._system_message(), {"role": "user", "content": request_tokens}]
        for obs in history:
            msgs.append({"role": "user", "content": f"OBSERVATION: {obs}"})
        return msgs

    def _parse(self, raw: str) -> Proposal:
        data = json.loads(raw)  # lève JSONDecodeError si invalide
        if "final" in data:
            return Finish(summary=str(data["final"]))
        action = data["action"]  # lève KeyError si absent
        intention = Intention(
            capability=action["capability"], args=action.get("args", {}), rationale=""
        )
        self._catalog.validate_intention(intention)  # lève UnknownCapability/MissingArgs
        return Act(intention=intention)

    async def propose(self, request_tokens: str, history: list[str]) -> Proposal:
        """Interroge le LLM et renvoie une proposition validée, avec relance bornée."""
        messages = self._base_messages(request_tokens, history)
        last_error = ""
        for _attempt in range(self._max_retries + 1):
            if last_error:
                messages = [
                    *self._base_messages(request_tokens, history),
                    {
                        "role": "user",
                        "content": (
                            f"Ta réponse précédente était invalide ({last_error}). "
                            "Recommence en JSON strict."
                        ),
                    },
                ]
            raw = await self._llm.chat(messages)
            try:
                return self._parse(raw)
            except (
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValidationError,
                UnknownCapability,
                MissingArgs,
            ) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
        raise ProposerError(last_error)
