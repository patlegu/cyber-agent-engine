"""
Mixin pour la gestion des tâches planifiées (Cron) OPNsense.
"""

from typing import Dict, Any, Literal
from ._decorators import safety_snapshot

class CronMixin:
    """
    Fonctionnalités OPNsense pour Cron (Automation & Scheduling).
    """

    def _get_cron_tools(self) -> list[Dict[str, Any]]:
        """Définitions OAk des outils Cron."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "schedule_cron_job",
                    "description": "Créer une nouvelle tâche planifiée (Cron) sur OPNsense.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "La commande interne OPNsense à exécuter (ex: 'configd_reboot', 'update_bogons')."
                            },
                            "parameters": {
                                "type": "string",
                                "description": "Paramètres optionnels passés à la commande (vide par défaut).",
                                "default": ""
                            },
                            "description": {
                                "type": "string",
                                "description": "Une description textuelle de l'objectif de cette tâche."
                            },
                            "minutes": {
                                "type": "string",
                                "description": "Spécification des minutes (ex: '0', '*/5', '*'). Défaut: '*'",
                                "default": "*"
                            },
                            "hours": {
                                "type": "string",
                                "description": "Spécification des heures (ex: '2', '*/2', '*'). Défaut: '*'",
                                "default": "*"
                            },
                            "days": {
                                "type": "string",
                                "description": "Spécification des jours (ex: '1', '15', '*'). Défaut: '*'",
                                "default": "*"
                            }
                        },
                        "required": ["command", "description"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "toggle_cron_job",
                    "description": "Activer ou désactiver une tâche Cron existante par son UUID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "uuid": {
                                "type": "string",
                                "description": "L'UUID unique de la tâche Cron."
                            },
                            "enabled": {
                                "type": "integer",
                                "description": "1 pour activer, 0 pour désactiver."
                            }
                        },
                        "required": ["uuid", "enabled"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_cron_jobs",
                    "description": "Lister toutes les tâches planifiées existantes sur le pare-feu.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            }
        ]

    # ========================================================================
    # Implémentations
    # ========================================================================

    async def get_cron_jobs(self, _arguments: dict) -> str:
        res = await self.client.get_cron_jobs()
        return self._format_json(res)

    @safety_snapshot
    async def schedule_cron_job(self, arguments: dict) -> str:
        res = await self.client.schedule_cron_job(
            command=arguments['command'],
            parameters=arguments.get('parameters', ""),
            description=arguments['description'],
            minutes=arguments.get('minutes', "*"),
            hours=arguments.get('hours', "*"),
            days=arguments.get('days', "*")
        )
        return self._format_json(res)

    @safety_snapshot
    async def toggle_cron_job(self, arguments: dict) -> str:
        res = await self.client.toggle_cron_job(
            uuid=arguments['uuid'],
            enabled=arguments['enabled']
        )
        return self._format_json(res)
