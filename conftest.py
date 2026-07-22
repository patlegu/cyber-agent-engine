"""
conftest.py — Configuration pytest globale.

Gère les dépendances manquantes et les imports problématiques.
"""

import sys
from unittest.mock import MagicMock

# Mock les modules manquants pour éviter les erreurs d'import
sys.modules['factory'] = MagicMock()
sys.modules['factory.clients'] = MagicMock()
