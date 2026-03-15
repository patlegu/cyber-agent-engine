"""
agents/crowdsec_agent.py

Agent-outil pour CrowdSec IDPS (Intrusion Detection & Prevention System).
Exposé sous le nom d'outil "crowdsec" dans l'API HTTP (/capabilities, /agent/execute).

---

## Fonctions exposées (15)

### Via LAPI REST (http://localhost:8080/v1)

| Nom              | Description courte                              | requires_approval |
|------------------|-------------------------------------------------|:-----------------:|
| ban_ip           | Bannit une IP via LAPI CrowdSec                 | oui               |
| unban_ip         | Lève le ban sur une IP                          | oui               |
| get_decisions    | Liste les décisions actives (filtres enrichis)  | non               |
| add_decision     | Ajoute une décision typée (ban, captcha…)       | oui               |
| delete_decision  | Supprime une décision par ID                    | oui               |
| get_alerts       | Consulte les alertes (filtres enrichis)         | non               |
| get_alert        | Détail d'une alerte par son ID                  | non               |
| delete_alert     | Supprime une alerte (faux positif)              | oui               |
| get_allowlists   | Liste les allowlists configurées                | non               |
| check_allowlist  | Vérifie si une IP/plage est dans une allowlist  | non               |

### Via cscli (subprocess local)

| Nom              | Description courte                              | requires_approval |
|------------------|-------------------------------------------------|:-----------------:|
| list_bouncers    | Liste les bouncers (composants de remédiation)  | non               |
| list_machines    | Liste les machines (agents log processors)      | non               |
| get_metrics      | Métriques parseurs/scénarios/bouncers           | non               |
| hub_upgrade      | Met à jour le contenu du hub CrowdSec           | oui               |
| set_simulation   | Active/désactive le mode simulation             | oui               |

---

## Ajouter une fonction

1. Définir la méthode dans cette classe :

       async def _ma_fonction(self, param: str) -> Dict:
           \"\"\"Résumé une ligne (extrait comme `description` dans get_capabilities()).

           :param param: Description affichée dans le schéma JSON exposé au LLM.
               Utiliser Literal["a", "b"] pour les valeurs restreintes → enum dans le schéma.
           \"\"\"

   Conventions :
   - Nom en snake_case, préfixé `_` (l'entrée dans `_register_functions` l'expose sans `_`).
   - Utiliser `:param name:` et non `Args:` — c'est le format lu par `_parse_param_docs()` dans base.py.
   - `Literal["v1", "v2"]` sur le type → enum dans le schéma OpenAI function-calling.

2. Enregistrer dans `_register_functions()` :

       "ma_fonction": self._ma_fonction,

---

## Mode simulation

Si `CROWDSEC_API_KEY` est absent ou si le client échoue à s'initialiser, l'agent retourne
des réponses simulées `{"mode": "simulation", ...}`. Utile pour les tests CI sans LAPI active.
"""


import logging
import os
from typing import Dict, List, Literal, Optional

from .base import ToolAgent, FunctionCall
try:
    from factory.clients.crowdsec_client import CrowdSecClient, CrowdSecAPIError
except ImportError:
    CrowdSecClient = None
    pass

logger = logging.getLogger(__name__)

class CrowdSecAgent(ToolAgent):
    """
    Agent-outil pour CrowdSec IDPS.
    """

    agent_role  = "CrowdSec IDPS agent"
    chat_format = "qwen"
    system_prompt = (
        "Tu es un agent CrowdSec. Tu reçois des directives structurées du coordinateur "
        "sous forme de paquets JSON (format CAP v1 : directive + entities + args) et tu génères "
        "des appels d'API précis sous forme de tool_calls. "
        "Tu ne réponds jamais en langage naturel — uniquement des tool_calls."
    )

    def __init__(
        self,
        model_path: str,
        api_config: Optional[Dict] = None,
        ollama_config: Optional[Dict] = None,
        vllm_client=None,
    ):
        super().__init__(
            tool_name="crowdsec",
            model_path=model_path,
            api_config=api_config,
            ollama_config=ollama_config,
            vllm_client=vllm_client,
        )
        self.client = None
        self._init_client()

    def _init_client(self):
        if self.api_config and self.api_config.get("api_key") and CrowdSecClient:
            try:
                self.client = CrowdSecClient(
                    api_key=self.api_config.get("api_key"),
                    base_url=self.api_config.get("base_url", "http://localhost:8080/v1"),
                    verify_ssl=self.api_config.get("verify_ssl", False),
                    cscli_path=self.api_config.get("cscli_path", "cscli"),
                )
                logger.info("CrowdSec Client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize CrowdSec Client: {e}")
                self.client = None
        else:
            logger.warning("CrowdSec API config missing or incomplete. Using simulation mode.")

    def _build_chat_messages(self, user_request: str) -> List[Dict]:
        """
        Construit les messages pour le chat Ollama.
        Surcharge pour utiliser le prompt Français ReAct (format d'entraînement).
        """
        functions_list = sorted(self._functions.keys())
        
        system_prompt = """Tu es un expert CrowdSec.

1. ANALYSE: Comprends la demande.
2. ACTION: Choisis la fonction JSON appropriée.

Fonctions valides: {}
""".format(', '.join(functions_list))

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_request}
        ]

    async def _infer_with_ollama(self, user_request: str) -> FunctionCall:
        """Inférence via Ollama API avec stop tokens spécifiques."""
        try:
            # On utilise le même prompt builder
            messages = self._build_chat_messages(user_request)
            
            model_name = self.ollama_config['model']
            logger.info(f"Appel Ollama ({model_name}) [CrowdSec Optimized]...")
            
            # Paramètres spécifiques pour CrowdSec LoRA qui semble boucler sans stop tokens explicites
            options_params = {
                "temperature": 0.1,
                "top_p": 0.9,
                "stop": ["OBSERVATION:", "Observation:", "RÉPONSE:", "[/INST]", "</s>", "<|endoftext|>", "Checking"],
                "num_predict": 256
            }
            
            # Wrap dans "options" car OllamaClient déballe le dictionnaire dans le payload
            response = self.ollama_client.chat(
                model=model_name,
                messages=messages,
                options={"options": options_params}
            )
            
            content = response.get('message', {}).get('content', '')
            logger.info(f"Réponse Ollama: {content[:100]}...")
            
            return self._parse_model_output(content, user_request)
            
        except Exception as e:
            logger.error(f"Erreur inférence Ollama: {e}")
            return await self._infer_with_simulation(user_request)

    def _register_functions(self) -> Dict[str, callable]:
        """Enregistre les fonctions CrowdSec."""
        return {
            "ban_ip": self._ban_ip,
            "unban_ip": self._unban_ip,
            "get_decisions": self._get_decisions,
            "add_decision": self._add_decision,
            "delete_decision": self._delete_decision,
            "get_alerts": self._get_alerts,
            "get_alert": self._get_alert,
            "delete_alert": self._delete_alert,
            "get_allowlists": self._get_allowlists,
            "check_allowlist": self._check_allowlist,
            # cscli
            "list_bouncers": self._list_bouncers,
            "list_machines": self._list_machines,
            "get_metrics": self._get_metrics,
            "hub_upgrade": self._hub_upgrade,
            "set_simulation": self._set_simulation,
        }

    async def _ban_ip(
        self,
        ip: str,
        duration: str = "4h",
        reason: str = "manual ban",
        scenario: str = "manual"
    ) -> Dict:
        """Bannit une adresse IP via CrowdSec LAPI.

        :param ip: Adresse IP à bannir (ex: "203.0.113.45").
        :param duration: Durée du bannissement au format Go duration (ex: "4h", "24h", "168h").
            Valeurs courantes : "1h" (1 heure), "4h" (4 heures), "24h" (1 jour), "168h" (1 semaine).
        :param reason: Motif lisible du bannissement (ex: "tentatives SSH répétées").
        :param scenario: Scénario CrowdSec associé (ex: "crowdsecurity/ssh-bf").
            Utiliser "manual" pour un ban manuel sans scénario.
        """
        logger.info(f"[CrowdSec] Bannissement IP: {ip} (durée: {duration})")

        if self.client:
            try:
                # add_decision normally matches ban_ip intent
                result = self.client.add_decision(value=ip, duration=duration, reason=reason, type="ban")
                return {"status": "banned", "result": result}
            except Exception as e:
                logger.error(f"Error banning IP: {e}")
                return {"status": "error", "message": str(e)}

        return {
            "status": "banned",
            "ip": ip,
            "duration": duration,
            "scenario": scenario,
            "mode": "simulation"
        }

    async def _unban_ip(self, ip: str) -> Dict:
        """Supprime toutes les décisions de bannissement actives pour une adresse IP.

        :param ip: Adresse IP à débannir (ex: "203.0.113.45").
        """
        logger.info(f"[CrowdSec] Débannissement IP: {ip}")

        if self.client:
            try:
                result = self.client.delete_decision_by_ip(ip)
                return {"status": "unbanned", "result": result}
            except Exception as e:
                logger.error(f"Error unbanning IP: {e}")
                return {"status": "error", "message": str(e)}

        return {
            "status": "unbanned",
            "ip": ip,
            "mode": "simulation"
        }

    async def _get_decisions(
        self,
        ip: Optional[str] = None,
        scope: Optional[str] = None,
        type: Optional[str] = None,
        range: Optional[str] = None,
        origins: Optional[str] = None,
        scenarios_containing: Optional[str] = None,
        limit: int = 100,
    ) -> Dict:
        """Liste les décisions actives (IPs bannies, durée restante, scénario déclencheur).

        :param ip: Filtre sur une IP précise (ex: "203.0.113.45"). Omis = toutes les décisions.
        :param scope: Portée des décisions à retourner (ex: "ip", "range", "country").
        :param type: Type de décision à filtrer (ex: "ban", "captcha").
        :param range: Filtre sur une plage CIDR (ex: "198.51.100.0/24").
        :param origins: Origines à inclure, séparées par virgule (ex: "cscli,crowdsec").
        :param scenarios_containing: Mots-clés séparés par virgule pour filtrer les scénarios
            (ex: "ssh,brute"). Retourne uniquement les décisions dont le scénario contient ces mots.
        :param limit: Nombre maximum de décisions à retourner (défaut : 100).
        """
        logger.info(f"[CrowdSec] Consultation décisions (limit: {limit})")

        if self.client:
            try:
                result = self.client.get_decisions(
                    ip=ip, scope=scope, type=type, range=range,
                    origins=origins, scenarios_containing=scenarios_containing,
                    limit=limit,
                )
                return {"total": len(result) if isinstance(result, list) else 0, "decisions": result}
            except Exception as e:
                logger.error(f"Error fetching decisions: {e}")
                return {"status": "error", "message": str(e)}

        return {
            "total": 1,
            "decisions": [
                {
                    "id": 123,
                    "origin": "cscli",
                    "type": "ban",
                    "scope": "ip",
                    "value": "203.0.113.45",
                    "duration": "4h",
                    "scenario": "crowdsecurity/ssh-bf",
                }
            ],
            "mode": "simulation",
        }

    async def _add_decision(
        self,
        value: str,
        type: Literal["ban", "captcha"] = "ban",
        duration: str = "4h",
        scope: Literal["ip", "range", "country"] = "ip",
        scenario: str = "manual"
    ) -> Dict:
        """Ajoute une décision manuelle dans CrowdSec LAPI.

        :param value: Cible de la décision selon le scope : IP (ex: "203.0.113.45"),
            plage CIDR (ex: "203.0.113.0/24") ou code pays ISO (ex: "CN").
        :param type: Type de remédiation : 'ban' (blocage total) ou 'captcha' (challenge CAPTCHA).
        :param duration: Durée au format Go duration (ex: "4h", "24h", "168h").
        :param scope: Périmètre de la décision : 'ip' (adresse seule), 'range' (CIDR),
            'country' (pays entier via code ISO-3166-1).
        :param scenario: Scénario associé (ex: "crowdsecurity/ssh-bf"). Utiliser "manual" si aucun.
        """
        logger.info(f"[CrowdSec] Ajout décision: {type} {scope}={value} ({duration})")

        if self.client:
            try:
                result = self.client.add_decision(
                    value=value, duration=duration, reason=scenario,
                    type=type, scope=scope
                )
                return {"status": "added", "result": result}
            except Exception as e:
                logger.error(f"Error adding decision: {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "added", "type": type, "scope": scope, "value": value,
                "duration": duration, "mode": "simulation"}

    async def _delete_decision(self, decision_id: int) -> Dict:
        """Supprime une décision CrowdSec par son identifiant numérique.

        :param decision_id: Identifiant de la décision (visible dans get_decisions).
        """
        logger.info(f"[CrowdSec] Suppression décision: {decision_id}")
        
        if self.client:
            try:
                result = self.client.delete_decision(decision_id)
                return {"status": "deleted", "result": result}
            except Exception as e:
                return {"status": "error", "message": str(e)}
                
        return {"status": "deleted", "id": decision_id, "mode": "simulation"}

    async def _get_alerts(
        self,
        limit: int = 100,
        ip: Optional[str] = None,
        range: Optional[str] = None,
        scenario: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        has_active_decision: Optional[bool] = None,
        decision_type: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> Dict:
        """Liste les alertes de détection CrowdSec (attaques détectées par les parseurs).

        :param limit: Nombre maximum d'alertes à retourner (défaut : 100).
        :param ip: Filtre sur une IP source précise (ex: "203.0.113.45").
        :param range: Filtre sur une plage CIDR source (ex: "198.51.100.0/24").
        :param scenario: Filtre sur un scénario exact (ex: "crowdsecurity/ssh-bf").
        :param since: Alertes plus récentes que cette date. Format RFC3339 (ex: "2026-01-01T00:00:00Z")
            ou durée relative (ex: "24h", "7d").
        :param until: Alertes plus anciennes que cette date. Même format que since.
        :param has_active_decision: Si True, retourne uniquement les alertes avec une décision active.
        :param decision_type: Filtre sur le type de décision associé (ex: "ban", "captcha").
        :param origin: Filtre sur l'origine de l'alerte (ex: "crowdsec", "cscli").
        """
        logger.info(f"[CrowdSec] Consultation alertes (limit: {limit})")

        if self.client:
            try:
                result = self.client.get_alerts(
                    limit=limit, ip=ip, range=range, scenario=scenario,
                    since=since, until=until, has_active_decision=has_active_decision,
                    decision_type=decision_type, origin=origin,
                )
                return {"total": len(result) if isinstance(result, list) else 0, "alerts": result}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {
            "total": 1,
            "alerts": [
                {
                    "id": 1001,
                    "scenario": "crowdsecurity/ssh-bf",
                    "source": {"ip": "203.0.113.45", "value": "203.0.113.45"},
                    "events_count": 15,
                    "created_at": "2026-01-12T09:15:23Z",
                }
            ],
            "mode": "simulation",
        }

    async def _get_alert(self, alert_id: int) -> Dict:
        """Retourne le détail complet d'une alerte par son identifiant numérique.

        :param alert_id: Identifiant numérique de l'alerte (visible dans get_alerts).
        """
        logger.info(f"[CrowdSec] Consultation alerte: {alert_id}")

        if self.client:
            try:
                result = self.client.get_alert(alert_id)
                return {"alert": result}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {
            "alert": {
                "id": alert_id,
                "scenario": "crowdsecurity/ssh-bf",
                "source": {"ip": "203.0.113.45"},
                "events_count": 15,
                "created_at": "2026-01-12T09:15:23Z",
            },
            "mode": "simulation",
        }

    async def _delete_alert(self, alert_id: int) -> Dict:
        """Supprime une alerte CrowdSec par son identifiant (ex: faux positif).

        :param alert_id: Identifiant numérique de l'alerte à supprimer (visible dans get_alerts).
        """
        logger.info(f"[CrowdSec] Suppression alerte: {alert_id}")

        if self.client:
            try:
                result = self.client.delete_alert(alert_id)
                return {"status": "deleted", "result": result}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {"status": "deleted", "id": alert_id, "mode": "simulation"}

    async def _get_allowlists(self) -> Dict:
        """Liste toutes les allowlists (listes blanches) configurées dans CrowdSec."""
        logger.info("[CrowdSec] Consultation allowlists")

        if self.client:
            try:
                result = self.client.get_allowlists()
                return {"total": len(result) if isinstance(result, list) else 0, "allowlists": result}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {
            "total": 1,
            "allowlists": [{"name": "my_allowlist", "description": "IPs de confiance"}],
            "mode": "simulation",
        }

    async def _check_allowlist(self, ip_or_range: str) -> Dict:
        """Vérifie si une IP ou une plage CIDR est présente dans une allowlist CrowdSec.

        :param ip_or_range: Adresse IP (ex: "192.168.1.10") ou plage CIDR (ex: "192.168.1.0/24")
            à vérifier dans les allowlists configurées.
        """
        logger.info(f"[CrowdSec] Vérification allowlist: {ip_or_range}")

        if self.client:
            try:
                result = self.client.check_allowlist(ip_or_range)
                return {"ip_or_range": ip_or_range, "result": result}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {
            "ip_or_range": ip_or_range,
            "result": {"allowlisted": False},
            "mode": "simulation",
        }

    # ------------------------------------------------------------------
    # cscli — fonctions locales (bouncers, machines, métriques, hub, simulation)
    # ------------------------------------------------------------------

    async def _list_bouncers(self) -> Dict:
        """Liste les bouncers (composants de remédiation) enregistrés dans CrowdSec."""
        logger.info("[CrowdSec] Listing bouncers via cscli")

        if self.client:
            try:
                result = self.client.list_bouncers()
                return {"total": len(result), "bouncers": result}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {
            "total": 1,
            "bouncers": [{"name": "firewall-bouncer", "ip_address": "127.0.0.1", "type": "crowdsec-firewall-bouncer"}],
            "mode": "simulation",
        }

    async def _list_machines(self) -> Dict:
        """Liste les machines (agents log processors) enregistrées dans CrowdSec."""
        logger.info("[CrowdSec] Listing machines via cscli")

        if self.client:
            try:
                result = self.client.list_machines()
                return {"total": len(result), "machines": result}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {
            "total": 1,
            "machines": [{"machineId": "localhost", "ipAddress": "127.0.0.1", "isValidated": True}],
            "mode": "simulation",
        }

    async def _get_metrics(self) -> Dict:
        """Retourne les métriques CrowdSec (parseurs, scénarios, activité des bouncers)."""
        logger.info("[CrowdSec] Getting metrics via cscli")

        if self.client:
            try:
                result = self.client.get_metrics()
                return {"metrics": result}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {
            "metrics": {
                "acquisition": {},
                "parsers": {},
                "scenarios": {},
                "lapi": {},
            },
            "mode": "simulation",
        }

    async def _hub_upgrade(self, force: bool = False) -> Dict:
        """Met à jour le contenu du hub CrowdSec (parseurs, scénarios, postoverflows).

        :param force: Si True, force le re-téléchargement même si déjà à jour.
        """
        logger.info(f"[CrowdSec] Hub upgrade via cscli (force={force})")

        if self.client:
            try:
                result = self.client.hub_upgrade(force=force)
                return {"status": "upgraded", **result}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {"status": "upgraded", "output": "Hub is up to date.", "mode": "simulation"}

    async def _set_simulation(
        self,
        action: Literal["enable", "disable"],
        scenario: Optional[str] = None,
    ) -> Dict:
        """Active ou désactive le mode simulation CrowdSec.

        En mode simulation, CrowdSec analyse et logue les menaces sans créer de décisions.

        :param action: 'enable' pour activer, 'disable' pour désactiver.
        :param scenario: Nom du scénario ciblé (ex: "crowdsecurity/ssh-bf").
            Si omis, applique le mode simulation globalement à tous les scénarios.
        """
        logger.info(f"[CrowdSec] Simulation {action} (scénario: {scenario or 'global'})")

        if self.client:
            try:
                result = self.client.set_simulation(action=action, scenario=scenario)
                return {"status": "ok", **result}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return {
            "status": "ok",
            "action": action,
            "scenario": scenario or "global",
            "mode": "simulation",
        }
