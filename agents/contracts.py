"""
agents/contracts.py — Contrats Pydantic partagés entre le tool-agent-server et le coordinateur.

Ces modèles garantissent que les deux côtés parlent le même schéma JSON.
Toute modification ici affecte simultanément server.py et coordinator/.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from agents.errors import ErrorCode


# ---------------------------------------------------------------------------
# Requête POST /agent/execute
# ---------------------------------------------------------------------------

class AgentExecuteRequest(BaseModel):
    """
    Requête d'exécution vers le tool-agent-server.

    Deux modes mutuellement inclusifs :
    - **Naturel** : `command` en langage naturel → le vLLM de l'agent l'interprète
    - **Structuré** : `function` + `args` → l'agent exécute directement, sans LLM

    Au moins l'un des deux doit être fourni.
    """
    command: Optional[str] = Field(
        default=None,
        description="Commande en langage naturel (mode naturel).",
    )
    function: Optional[str] = Field(
        default=None,
        description="Nom de la fonction à appeler directement (mode structuré).",
    )
    args: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments à passer à la fonction en mode structuré.",
    )

    @model_validator(mode="after")
    def require_command_or_function(self) -> AgentExecuteRequest:
        if not self.command and not self.function:
            raise ValueError("Either 'command' or 'function' must be provided.")
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
    success: bool
    tool_name: str = ""
    function: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
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
