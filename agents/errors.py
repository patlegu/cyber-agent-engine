# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Codes d'erreur structurés pour les agents-outils.

Permet au coordinateur d'agents de prendre des décisions intelligentes :
  - FUNCTION_UNKNOWN  → l'agent n'a pas compris la demande, essayer un autre agent
  - MISSING_ARG       → le coordinateur doit compléter les paramètres avant de réessayer
  - API_UNREACHABLE   → réessayer plus tard (backoff), ne pas escalader
  - PERMISSION_DENIED → escalader à l'opérateur humain
  - EXECUTION_ERROR   → erreur inattendue, logger et escalader
  - INFERENCE_FAILED  → le backend LoRA/vLLM a échoué, basculer sur Ollama ou simulation
"""

from enum import Enum


class ErrorCode(str, Enum):
    """Code d'erreur retourné par ToolResult en cas d'échec."""

    FUNCTION_UNKNOWN   = "FUNCTION_UNKNOWN"
    """Le LoRA ou le parsing n'a pas pu identifier la fonction à appeler."""

    MISSING_ARG        = "MISSING_ARG"
    """Au moins un argument obligatoire est absent de la réponse du modèle."""

    EXECUTION_ERROR    = "EXECUTION_ERROR"
    """Exception imprévue pendant l'exécution de la fonction."""

    API_UNREACHABLE    = "API_UNREACHABLE"
    """Timeout ou connexion refusée vers l'équipement cible."""

    PERMISSION_DENIED  = "PERMISSION_DENIED"
    """L'équipement a retourné HTTP 401 ou 403."""

    INFERENCE_FAILED   = "INFERENCE_FAILED"
    """Le backend d'inférence (vLLM, Ollama, LoRA) a échoué."""
