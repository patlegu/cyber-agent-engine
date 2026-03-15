"""
Agents-outils pour sécurité réseau.

Ce package fournit des agents spécialisés pour différents outils de sécurité :
- OPNsenseAgent : Firewall OPNsense (40 fonctions)
- StormshieldAgent : Firewall Stormshield SNS (7 fonctions)
- CrowdSecAgent : CrowdSec IDPS (6 fonctions)

Chaque agent utilise un LoRA dédié pour décider quelle fonction appeler
et avec quels paramètres.

Example:
    >>> from factory.agents import OPNsenseAgent
    >>> agent = OPNsenseAgent('models/opnsense_lora/adapter')
    >>> result = await agent.execute("Créer une règle pour bloquer 10.0.0.50")
"""

from .base import ToolAgent, FunctionCall, ToolResult
from .opnsense_agent import OPNsenseAgent
from .pfsense_agent import PfSenseAgent
from .stormshield_agent import StormshieldAgent
from .crowdsec_agent import CrowdSecAgent
from .wireguard_agent import WireGuardAgent

from typing import Dict, Optional

__all__ = [
    # Classes de base
    'ToolAgent',
    'FunctionCall',
    'ToolResult',
    
    # Agents spécialisés
    'OPNsenseAgent',
    'PfSenseAgent',
    'StormshieldAgent',
    'CrowdSecAgent',
    'WireGuardAgent',
    
    # Factory
    'create_agent',
]

def create_agent(
    tool_type: str,
    model_path: str,
    api_config: Optional[Dict] = None
) -> ToolAgent:
    """
    Factory pour créer un agent-outil.

    Args:
        tool_type: Type d'outil ("stormshield", "opnsense", "crowdsec")
        model_path: Chemin vers le modèle LoRA
        api_config: Configuration API (optionnel)

    Returns:
        Instance de l'agent approprié

    Raises:
        ValueError: Si le type d'agent est inconnu

    Example:
        >>> agent = create_agent("opnsense", "models/opnsense_lora/adapter")
        >>> result = await agent.execute("Lister les règles de filtrage")
        
        >>> # Avec configuration API
        >>> from config.opnsense_config import OPNSENSE_CONFIG
        >>> agent = create_agent(
        ...     "opnsense",
        ...     "models/opnsense_lora/adapter",
        ...     api_config=OPNSENSE_CONFIG
        ... )
    """
    agents = {
        "stormshield": StormshieldAgent,
        "opnsense": OPNsenseAgent,
        "pfSense": PfSenseAgent,
        "crowdsec": CrowdSecAgent,
    }

    if tool_type not in agents:
        raise ValueError(
            f"Type d'agent inconnu: {tool_type}. "
            f"Types supportés: {list(agents.keys())}"
        )

    return agents[tool_type](model_path=model_path, api_config=api_config)
