"""
DEPRECATED: Ce fichier est déprécié depuis janvier 2026.

Les agents ont été réorganisés en fichiers séparés pour une meilleure maintenabilité.

Utilisez les imports suivants à la place :
    from agents import OPNsenseAgent
    from agents import StormshieldAgent
    from agents import CrowdSecAgent
    from agents import create_agent

Structure modulaire :
    agents/
    ├── __init__.py                # Exports publics
    ├── base.py                    # ToolAgent (classe de base)
    ├── opnsense_agent.py         # OPNsenseAgent (40 fonctions)
    ├── stormshield_agent.py      # StormshieldAgent (7 fonctions)
    └── crowdsec_agent.py         # CrowdSecAgent (6 fonctions)

Pour plus d'informations, consultez docs/AGENTS_REFACTORING.md
"""

import warnings

# Imports pour compatibilité ascendante
from .base import ToolAgent, FunctionCall, ToolResult
from .opnsense_agent import OPNsenseAgent
from .stormshield_agent import StormshieldAgent
from .crowdsec_agent import CrowdSecAgent
from . import create_agent

# Avertissement de dépréciation
warnings.warn(
    "tool_agents.py est déprécié. "
    "Utilisez 'from agents import OPNsenseAgent' à la place. "
    "Voir docs/AGENTS_REFACTORING.md pour plus de détails.",
    DeprecationWarning,
    stacklevel=2
)

__all__ = [
    'ToolAgent',
    'FunctionCall',
    'ToolResult',
    'OPNsenseAgent',
    'StormshieldAgent',
    'CrowdSecAgent',
    'create_agent',
]
