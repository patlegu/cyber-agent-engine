# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Classifieur d'intention pour le routage vers l'agent approprié.

Remplace le routage par mots-clés simples de server.py par un scoring
pondéré qui résiste mieux aux cas ambigus (ex: "VPN rule on firewall",
"block a key IP", "unblock wireguard peer").
"""

from typing import Dict, Tuple


class AgentClassifier:
    """
    Classifie une commande utilisateur vers l'agent cible via scoring pondéré.

    Chaque agent dispose d'une liste de mots-clés répartis en 4 catégories :
    - strong   : indicateur très fort (+3)
    - medium   : indicateur modéré (+2)
    - weak     : indice léger (+1)
    - negative : contre-indicateur (−2), réduit le score de cet agent

    L'agent avec le score le plus élevé est sélectionné.
    En cas d'égalité ou de score nul, OPNsense est retourné par défaut.
    """

    AGENT_KEYWORDS: Dict[str, Dict[str, list]] = {
        "wireguard": {
            "strong": [
                "wireguard", "wiregaurd", "wg",  # typo inclus
                "tunnel", "peer", "mesh", "psk", "pre-shared key",
                "site-to-site", "point-to-point", "handshake",
            ],
            "medium": [
                "vpn", "clé vpn", "cle vpn", "vpn key",
                "keepalive", "endpoint", "allowed ips", "allowed-ips",
            ],
            "weak": [
                "clé", "clef", "key", "interface wg",
            ],
            "negative": [
                "firewall", "alias", "nat", "règle firewall", "ban",
                "crowdsec", "blocklist",
            ],
        },
        "crowdsec": {
            "strong": [
                "crowdsec", "cscli",
                "ban ip", "unban ip", "bannir", "débannir",
                "decision", "décision", "scenario", "scénario",
            ],
            "medium": [
                "threat", "menace", "blocklist", "alerte", "alert",
                "intrusion", "attaque détectée",
            ],
            "weak": [
                "attaque", "malveillant", "ip suspecte",
            ],
            "negative": [
                "wireguard", "vpn", "tunnel", "nat", "alias",
            ],
        },
        "opnsense": {
            "strong": [
                "firewall", "opnsense", "filter rule", "règle firewall",
                "alias", "nat", "port forward", "outbound nat",
            ],
            "medium": [
                "règle", "rule", "acl", "protocol", "protocole",
                "interface", "geoip", "catégorie", "category",
                "sauvegarde", "backup", "rollback", "savepoint",
            ],
            "weak": [
                "bloquer", "block", "réseau", "network", "port",
                "adresse", "address",
            ],
            "negative": [],
        },
    }

    WEIGHTS: Dict[str, int] = {
        "strong": 3,
        "medium": 2,
        "weak": 1,
        "negative": -2,
    }

    def __init__(self, model_path: str = None):
        """Initialise le classifieur et charge le modèle NER si disponible."""
        import os
        import spacy
        from pathlib import Path

        if model_path is None:
            # Chemin par défaut relatif à la racine du projet
            root = Path(__file__).parent.parent
            model_path = str(root / "models" / "anonyner_model" / "model-best")

        self.nlp = None
        if os.path.exists(model_path):
            try:
                self.nlp = spacy.load(model_path)
            except Exception:
                pass

    def extract_entities(self, command: str) -> Dict[str, list]:
        """Extrait les entités nommées via AnonyNER."""
        if not self.nlp:
            return {}
        
        doc = self.nlp(command)
        entities = {}
        for ent in doc.ents:
            if ent.label_ not in entities:
                entities[ent.label_] = []
            entities[ent.label_].append(ent.text)
        return entities

    def classify(self, command: str) -> Tuple[str, float, Dict[str, list]]:
        """
        Classifie une commande et retourne (agent_name, confidence, entities).

        Args:
            command: Commande en langage naturel (FR ou EN)

        Returns:
            Tuple (nom_agent, score_de_confiance, entites_extraites)
        """
        cmd = command.lower()
        scores: Dict[str, float] = {agent: 0.0 for agent in self.AGENT_KEYWORDS}

        for agent, categories in self.AGENT_KEYWORDS.items():
            for category, keywords in categories.items():
                weight = self.WEIGHTS[category]
                for kw in keywords:
                    if kw in cmd:
                        scores[agent] += weight

        # Bonus de score si certaines entités sont présentes
        entities = self.extract_entities(command)
        
        # Si on détecte une interface "wg0" -> strong bonus pour WireGuard
        if "wg" in "".join(entities.get("INTERFACE", [])).lower():
            scores["wireguard"] += 3
        
        # Si on détecte une CVE -> strong bonus pour CrowdSec ou OPNsense (selon contexte)
        if entities.get("CVE"):
            scores["crowdsec"] += 2

        best_agent = max(scores, key=scores.get)

        if scores[best_agent] <= 0:
            return "opnsense", 0.0, entities

        total = sum(abs(s) for s in scores.values()) or 1.0
        confidence = min(1.0, scores[best_agent] / total)

        return best_agent, confidence, entities
