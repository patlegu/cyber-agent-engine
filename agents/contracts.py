"""
agents/contracts.py — Contrats Pydantic partagés entre le tool-agent-server et le coordinateur.

Ces modèles garantissent que les deux côtés parlent le même schéma JSON.
Toute modification ici affecte simultanément server.py et coordinator/.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents.errors import ErrorCode

_MAX_ARGS = 64
_MAX_KEY_LEN = 128
_MAX_VAL_LEN = 8192
_MAX_FUNCTION_LEN = 128


# ---------------------------------------------------------------------------
# Requête POST /agent/execute
# ---------------------------------------------------------------------------

class AgentExecuteRequest(BaseModel):
    """
    Requête d'exécution CAP v2. Mode structuré (`function`+`args`) sur la chaîne
    de confiance ; `command` (langage naturel) réservé au debug hors chaîne.
    """

    model_config = ConfigDict(extra="forbid")

    command: Optional[str] = Field(
        default=None,
        description="Commande NL (mode debug).",
    )
    function: Optional[str] = Field(
        default=None,
        description="Fonction à appeler (mode structuré).",
    )
    args: dict[str, str] = Field(
        default_factory=dict,
        description="Args structurés (str).",
    )

    @model_validator(mode="after")
    def _validate(self) -> AgentExecuteRequest:
        if not self.command and not self.function:
            raise ValueError("Either 'command' or 'function' must be provided.")
        if self.function is not None and len(self.function) > _MAX_FUNCTION_LEN:
            raise ValueError("function name too long")
        if len(self.args) > _MAX_ARGS:
            raise ValueError("too many args")
        for k, v in self.args.items():
            if len(k) > _MAX_KEY_LEN or len(v) > _MAX_VAL_LEN:
                raise ValueError(f"arg '{k}' exceeds size bound")
        return self


# ---------------------------------------------------------------------------
# Réponse POST /agent/execute
# ---------------------------------------------------------------------------

class AgentExecuteResponse(BaseModel):
    """
    Réponse standardisée du tool-agent-server.

    Utilisé par :
    - server.py pour construire et sérialiser les réponses
    - ToolAgentClient pour valider et typer les réponses reçues
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    tool_name: str = ""
    function: str = ""
    args: dict[str, str] = Field(default_factory=dict)
    result: Any = None
    error: Optional[str] = None
    error_code: Optional[ErrorCode] = None
    reasoning: str = ""
    execution_time_ms: float = 0.0

    def is_retryable(self) -> bool:
        """Vrai si l'erreur est transitoire et peut être retentée."""
        return self.error_code == ErrorCode.API_UNREACHABLE

    def is_missing_arg(self) -> bool:
        return self.error_code == ErrorCode.MISSING_ARG

    def is_permission_denied(self) -> bool:
        return self.error_code == ErrorCode.PERMISSION_DENIED
