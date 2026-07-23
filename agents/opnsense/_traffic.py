# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Mixin pour le Traffic Shaping OPNsense (QoS / dummynet) — 11 méthodes.

Gestion des pipes (limitation de bande passante), queues (priorisation)
et règles de classification du trafic.
"""

import logging
from typing import Dict

from ._decorators import safety_snapshot

logger = logging.getLogger(__name__)


class TrafficShaperMixin:

    async def _get_traffic_statistics(self) -> Dict:
        """Retourne les statistiques de bande passante en temps réel par pipe et queue.

        Utile pour monitorer l'utilisation des limitations de débit configurées.
        """
        logger.info("[OPNsense] Statistiques traffic shaping")
        if self._api_client:
            try:
                return await self._api_client.get_traffic_statistics()
            except Exception as e:
                logger.error(f"Erreur stats trafic: {e}")
                return {"status": "error", "message": str(e)}
        return {"pipes": [], "queues": [], "mode": "simulation"}

    async def _list_traffic_pipes(self) -> Dict:
        """Liste tous les pipes de traffic shaping configurés (limitation bande passante).

        Un pipe définit une limite de débit maximale (ex: 10 Mbit/s).
        """
        logger.info("[OPNsense] Liste des pipes traffic shaping")
        if self._api_client:
            try:
                return await self._api_client.list_traffic_pipes()
            except Exception as e:
                logger.error(f"Erreur liste pipes: {e}")
                return {"status": "error", "message": str(e)}
        return {"pipes": [], "mode": "simulation"}

    @safety_snapshot
    async def _add_traffic_pipe(
        self,
        description: str,
        bandwidth: int,
        bandwidth_metric: str = "Mbit",
    ) -> Dict:
        """Crée un pipe de traffic shaping pour limiter la bande passante.

        :param description: Nom descriptif du pipe (ex: 'Limite_Guest_10Mbit').
        :param bandwidth: Valeur numérique de la limite de bande passante.
        :param bandwidth_metric: Unité : 'Kbit', 'Mbit' (défaut) ou 'Gbit'.
        """
        logger.info(f"[OPNsense] Création pipe: {description} {bandwidth} {bandwidth_metric}")
        if self._api_client:
            try:
                response = await self._api_client.add_traffic_pipe(
                    description=description,
                    bandwidth=bandwidth,
                    bandwidth_metric=bandwidth_metric,
                )
                if response.get("uuid"):
                    await self._api_client.apply_traffic_changes()
                    logger.info(f"✓ Pipe '{description}' créé")
                return response
            except Exception as e:
                logger.error(f"Erreur création pipe: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "created", "description": description, "mode": "simulation"}

    @safety_snapshot
    async def _del_traffic_pipe(self, uuid: str) -> Dict:
        """Supprime un pipe de traffic shaping par son UUID.

        :param uuid: UUID du pipe à supprimer.
        """
        logger.info(f"[OPNsense] Suppression pipe: {uuid}")
        if self._api_client:
            try:
                response = await self._api_client.del_traffic_pipe(uuid)
                await self._api_client.apply_traffic_changes()
                return response
            except Exception as e:
                logger.error(f"Erreur suppression pipe: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "deleted", "uuid": uuid, "mode": "simulation"}

    async def _list_traffic_queues(self) -> Dict:
        """Liste toutes les queues de traffic shaping (priorisation intra-pipe).

        Une queue appartient à un pipe et définit une priorité relative.
        """
        logger.info("[OPNsense] Liste des queues traffic shaping")
        if self._api_client:
            try:
                return await self._api_client.list_traffic_queues()
            except Exception as e:
                logger.error(f"Erreur liste queues: {e}")
                return {"status": "error", "message": str(e)}
        return {"queues": [], "mode": "simulation"}

    @safety_snapshot
    async def _add_traffic_queue(
        self,
        description: str,
        pipe: str,
        weight: int = 100,
    ) -> Dict:
        """Crée une queue attachée à un pipe pour la priorisation du trafic.

        :param description: Nom descriptif de la queue (ex: 'VoIP_Prio').
        :param pipe: UUID du pipe parent auquel rattacher cette queue.
        :param weight: Poids relatif de la queue (1-100, plus élevé = plus prioritaire).
        """
        logger.info(f"[OPNsense] Création queue: {description} → pipe {pipe}")
        if self._api_client:
            try:
                response = await self._api_client.add_traffic_queue(
                    description=description,
                    pipe=pipe,
                    weight=weight,
                )
                if response.get("uuid"):
                    await self._api_client.apply_traffic_changes()
                    logger.info(f"✓ Queue '{description}' créée")
                return response
            except Exception as e:
                logger.error(f"Erreur création queue: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "created", "description": description, "mode": "simulation"}

    @safety_snapshot
    async def _del_traffic_queue(self, uuid: str) -> Dict:
        """Supprime une queue de traffic shaping par son UUID.

        :param uuid: UUID de la queue à supprimer.
        """
        logger.info(f"[OPNsense] Suppression queue: {uuid}")
        if self._api_client:
            try:
                response = await self._api_client.del_traffic_queue(uuid)
                await self._api_client.apply_traffic_changes()
                return response
            except Exception as e:
                logger.error(f"Erreur suppression queue: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "deleted", "uuid": uuid, "mode": "simulation"}

    async def _list_traffic_rules(self) -> Dict:
        """Liste les règles de classification du trafic vers les pipes/queues.

        Ces règles définissent quel trafic (IP/port/protocole) va dans quel pipe.
        """
        logger.info("[OPNsense] Liste des règles traffic shaping")
        if self._api_client:
            try:
                return await self._api_client.list_traffic_rules()
            except Exception as e:
                logger.error(f"Erreur liste règles trafic: {e}")
                return {"status": "error", "message": str(e)}
        return {"rules": [], "mode": "simulation"}

    @safety_snapshot
    async def _add_traffic_rule(
        self,
        description: str,
        sequence: int,
        target: str,
        source: str = "any",
        destination: str = "any",
    ) -> Dict:
        """Crée une règle de classification du trafic vers un pipe ou une queue.

        :param description: Nom descriptif de la règle.
        :param sequence: Numéro d'ordre d'évaluation (plus petit = prioritaire).
        :param target: UUID du pipe ou de la queue cible.
        :param source: Adresse/réseau source (ex: '192.168.1.0/24' ou 'any').
        :param destination: Adresse/réseau destination (ex: 'any').
        """
        logger.info(f"[OPNsense] Création règle trafic: {description} → {target}")
        if self._api_client:
            try:
                response = await self._api_client.add_traffic_rule(
                    description=description,
                    sequence=sequence,
                    target=target,
                    source=source,
                    destination=destination,
                )
                if response.get("uuid"):
                    await self._api_client.apply_traffic_changes()
                    logger.info(f"✓ Règle trafic '{description}' créée")
                return response
            except Exception as e:
                logger.error(f"Erreur création règle trafic: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "created", "description": description, "mode": "simulation"}

    @safety_snapshot
    async def _del_traffic_rule(self, uuid: str) -> Dict:
        """Supprime une règle de classification du trafic par son UUID.

        :param uuid: UUID de la règle à supprimer.
        """
        logger.info(f"[OPNsense] Suppression règle trafic: {uuid}")
        if self._api_client:
            try:
                response = await self._api_client.del_traffic_rule(uuid)
                await self._api_client.apply_traffic_changes()
                return response
            except Exception as e:
                logger.error(f"Erreur suppression règle trafic: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "deleted", "uuid": uuid, "mode": "simulation"}

    async def _apply_traffic_changes(self) -> Dict:
        """Applique et active toutes les modifications de traffic shaping en attente."""
        logger.info("[OPNsense] Application traffic shaping")
        if self._api_client:
            try:
                return await self._api_client.apply_traffic_changes()
            except Exception as e:
                logger.error(f"Erreur application traffic: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "applied", "mode": "simulation"}
