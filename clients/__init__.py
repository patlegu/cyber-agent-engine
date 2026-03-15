"""
Clients API pour les différents outils de sécurité réseau.
"""

from .opnsense_api_client import OPNsenseAPIClient, OPNsenseAPIError
from .pfsense_api_client import PfSenseAPIClient
from .wireguard_api_client import WireGuardAPIClient
from .wireguard_linux_client import WireGuardLinuxClient

# __all__ = ['OPNsenseAPIClient', 'OPNsenseAPIError']

__all__ = [
    'OPNsenseAPIClient',
    'OPNsenseAPIError',
    'PfSenseAPIClient',
    'WireGuardAPIClient',
    'WireGuardLinuxClient',
]
