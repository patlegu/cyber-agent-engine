"""
Décorateurs partagés pour les agents OPNsense.
"""

import functools
import logging

logger = logging.getLogger(__name__)


def safety_snapshot(func):
    """
    Crée automatiquement un point de sauvegarde avant toute action critique.

    Ne s'applique qu'en mode API connecté sur plateforme 'opnsense'.
    """
    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        if getattr(self, "_api_client", None) and getattr(self, "platform", "") == "opnsense":
            try:
                func_name = func.__name__.lstrip("_")
                logger.info(f"[Auto-Snapshot] Creating restore point before {func_name}")
                if func_name != "create_restore_point":
                    await self._create_restore_point(description=f"Auto-save: {func_name}")
            except Exception as e:
                logger.warning(f"[Auto-Snapshot] Failed to create restore point: {e}")
        return await func(self, *args, **kwargs)
    return wrapper
