"""
coordinator/pilot.py — PilotAgent, cerveau du coordinateur.

Responsabilités :
1. plan()         → LLM décompose la query en liste de Task
2. execute_plan() → exécute les tâches via ToolAgentClient, gère les erreurs
3. synthesize()   → LLM génère le rapport Markdown final

Gestion des error_code :
  MISSING_ARG      → reformule la commande (1 retry LLM), sinon FAILED
  API_UNREACHABLE  → ToolAgentClient gère le retry x2, arrive ici en FAILED
  PERMISSION_DENIED→ FAILED, noté dans le rapport
  FUNCTION_UNKNOWN → FAILED
  INFERENCE_FAILED → FAILED
  success          → DONE
"""

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .clients.tool_agent_client import ToolAgentClient, ToolAgentError
from .judge import CAPValidator
from .llm.coordinator_llm import CoordinatorLLM
from .models import CoordinatorDirective
from .state import PlanState, RunStatus, Task, TaskStatus, is_destructive


_READ_PREFIXES       = ("get_", "list_", "show_", "fetch_", "count_", "check_")
_WRITE_PREFIXES      = ("del_", "delete_", "disable_", "block_", "toggle_")

_READ_INTENT_WORDS   = (
    "liste", "lister", "affiche", "afficher", "montre", "montrer",
    "combien", "nombre", "count", "show", "display",
    "quelles", "quels", "consulte", "consulter",
)
_MUTATION_INTENT_WORDS = (
    "crée", "cree", "creer", "ajoute", "ajouter",
    "modifie", "modifier", "active", "activer",
    "configure", "configurer", "appliqu",
)


def _is_read_only_query(query: str) -> bool:
    """Retourne True si la query ne demande qu'une lecture (pas de mutation ni de destruction)."""
    lower = query.lower()
    if is_destructive(lower):
        return False
    if any(w in lower for w in _MUTATION_INTENT_WORDS):
        return False
    return any(w in lower for w in _READ_INTENT_WORDS)


def _needs_approval(directive: Optional[str], description: str) -> bool:
    """Détermine si une action nécessite une approbation humaine.

    La valeur du LLM (requires_approval) est IGNORÉE — seuls la directive et
    la description font foi.  Cela évite les faux positifs quand le LLM
    surclasse des lectures comme destructives.
    """
    if directive:
        if directive.startswith(_READ_PREFIXES):
            return False
        if directive.startswith(_WRITE_PREFIXES):
            return True
        # Directive inconnue : se rabattre sur le contenu de la description
    return is_destructive(description)

# Regex UUID canonique (RFC 4122) — utilisé pour détecter les UUIDs dans les reformulations
_UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)


@dataclass
class ReformulationResult:
    """
    Résultat d'une reformulation après échec MISSING_ARG.

    Quand un agent retourne MISSING_ARG (argument manquant ou invalide, ex: UUID inconnu),
    le coordinateur interroge son LLM en lui fournissant les résultats des tâches déjà
    exécutées comme contexte. Ce dataclass représente la décision prise.

    Modes possibles (par ordre de fiabilité décroissante) :

    - mode="structured" : le LLM a pu identifier précisément la fonction à appeler
                          et résoudre tous ses arguments (ex: UUID extrait d'un listing).
                          → execute_structured() est utilisé : bypass complet du LLM agent,
                            appel direct de la fonction. Chemin le plus fiable.

    - mode="natural"    : le LLM n'a pas pu résoudre les args précisément, mais a produit
                          une reformulation en langage naturel plus explicite.
                          → execute() est utilisé : la commande reformulée repasse par le
                            LLM de l'agent. Un retry guidé, moins fiable que structured.

    - mode=None         : reformulation impossible — information insuffisante, action
                          contradictoire, ou LLM a retourné {"mode": "impossible"}.
                          → La tâche est marquée en échec définitif.
    """
    # "structured" | "natural" | None
    mode: Optional[str] = None
    # Rempli si mode="natural" : commande reformulée en langage naturel
    natural_language: Optional[str] = None
    # Remplis si mode="structured" : nom de la fonction et ses arguments résolus
    function: Optional[str] = None
    args: dict[str, Any] = field(default_factory=dict)

    @property
    def is_structured(self) -> bool:
        """True si la reformulation a produit une fonction + args exploitables."""
        return self.mode == "structured" and bool(self.function)

    @property
    def is_natural(self) -> bool:
        """True si la reformulation a produit une commande en langage naturel."""
        return self.mode == "natural" and bool(self.natural_language)

logger = logging.getLogger(__name__)

# Chemin vers les prompts du coordinateur (dans ce package)
_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Correspondance mutation → listing pour l'injection automatique de listing
# Quand une mutation échoue sur uuid manquant et qu'aucun listing n'a été fait,
# on injecte automatiquement la directive de listing correspondante.
_MUTATION_TO_LISTING: dict[str, str] = {
    "del_filter_rule":      "get_filter_rule",
    "toggle_filter_rule":   "get_filter_rule",
    "update_filter_rule":   "get_filter_rule",
    "del_alias":            "get_alias",
    "add_to_alias":         "get_alias",
    "del_nat_port_forward": "get_nat_port_forward",
    "del_nat_outbound":     "get_nat_outbound",
    "del_static_route":     "get_static_route",
    "del_openvpn_server":   "get_openvpn_server",
    "del_openvpn_client":   "get_openvpn_client",
    "del_ipsec_tunnel":     "get_ipsec_tunnel",
    "del_haproxy_server":   "get_haproxy_server",
    "del_haproxy_backend":  "get_haproxy_backend",
    "del_haproxy_frontend": "get_haproxy_frontend",
    "del_acme_cert":        "get_acme_cert",
    "del_unbound_host":     "get_unbound_host",
    "del_dhcp_static":      "get_dhcp_static",
    "del_vlan":             "get_vlan",
    "del_wireguard_peer":   "get_wireguard_peer",
    "del_wireguard_server": "get_wireguard_server",
}

# Import du PromptLoader du projet parent
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.prompts.loader import PromptLoader
from agents.ner_extractor import NERExtractor


def _build_prompt_loader() -> PromptLoader:
    return PromptLoader(agent_name="coordinator", prompts_dir=_PROMPTS_DIR)


def _extract_json(text: str) -> dict:
    """Extrait le premier objet JSON valide d'une chaîne de texte."""
    # Chercher un bloc ```json ... ```
    match = re.search(r"```json\s*([\s\S]+?)```", text)
    if match:
        text = match.group(1)
    # Chercher la position du premier { et décoder avec raw_decode pour s'arrêter
    # proprement au premier objet JSON complet (évite "Extra data" si le LLM
    # émet du texte ou un second bloc JSON après l'objet principal).
    start = text.find("{")
    if start != -1:
        obj, _ = json.JSONDecoder().raw_decode(text, start)
        return obj
    raise ValueError(f"No JSON found in LLM output: {text[:200]}")


class PilotAgent:
    """
    Agent coordinateur haut niveau.

    init() doit être appelé avant toute utilisation (initialise le LLM).
    shutdown() libère les ressources à l'arrêt.
    """

    def __init__(self, tool_clients: dict[str, "ToolAgentClient"], llm: CoordinatorLLM):
        self._tools = tool_clients      # {"opnsense": client, "wireguard": client, …}
        self._llm = llm
        self._loader = _build_prompt_loader()
        self._capabilities: dict = {}   # rempli lors du premier appel à plan()
        self._ner = NERExtractor()      # extracteur NER pour construction des paquets CAP
        self._judge = CAPValidator()    # valide les paquets CAP avant exécution

    # ------------------------------------------------------------------
    # Point d'entrée principal
    # ------------------------------------------------------------------

    async def run(self, query: str) -> PlanState:
        """
        Exécute le pipeline complet : plan → execute → synthesize.

        Si des tâches nécessitent une approbation humaine, s'arrête avec
        status=CHECKPOINT_WAIT et retourne l'état pour que le serveur le stocke.
        L'appelant reprend avec resume_after_approval() une fois l'approbation reçue.
        """
        state = await self.plan(query)

        # Si le plan contient des actions destructives → checkpoint
        destructive = [t for t in state.tasks if t.requires_approval]
        if destructive:
            for t in destructive:
                t.status = TaskStatus.WAITING_APPROVAL
            state.status = RunStatus.CHECKPOINT_WAIT
            state.checkpoint_at = time.time()
            logger.info(
                "[%s] Checkpoint : %d tâche(s) en attente d'approbation",
                state.run_id, len(destructive),
            )
            return state

        return await self._execute_and_synthesize(state)

    async def resume_after_approval(self, state: PlanState) -> PlanState:
        """Reprend l'exécution après approbation humaine des checkpoints."""
        if state.react_mode:
            return await self._resume_react(state)
        # Mode plan statique : les tâches approuvées passent en PENDING
        for t in state.tasks:
            if t.status == TaskStatus.WAITING_APPROVAL and t.approved:
                t.status = TaskStatus.PENDING
            elif t.status == TaskStatus.WAITING_APPROVAL and t.approved is False:
                t.status = TaskStatus.REJECTED
        return await self._execute_and_synthesize(state)

    # ------------------------------------------------------------------
    # Étapes internes
    # ------------------------------------------------------------------

    async def plan(self, query: str) -> PlanState:
        """Appelle le LLM pour décomposer la query en liste de Task."""
        state = PlanState.new(query)
        state.status = RunStatus.PLANNING

        # Récupère un résumé agrégé des capacités de tous les agents
        try:
            caps = await self._fetch_capabilities()
            self._capabilities = caps   # conservé pour _reformulate
            self._judge.update(caps)
            caps_summary = self._summarize_capabilities(caps)
        except Exception as exc:
            logger.warning("Cannot fetch capabilities: %s", exc)
            self._capabilities = {}
            caps_summary = "opnsense (firewall), wireguard (vpn), crowdsec (idps)"

        system_prompt = self._loader.render("system")
        planning_prompt = self._loader.render(
            "planning",
            query=query,
            capabilities_summary=caps_summary,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": planning_prompt},
        ]

        try:
            raw = await self._llm.chat(messages, max_tokens=1024)
        except Exception as exc:
            backend = self._llm._backend
            hints = {
                "anthropic": "Vérifiez que ANTHROPIC_API_KEY est définie dans .env",
                "openai":    "Vérifiez OPENAI_API_KEY et OPENAI_BASE_URL dans .env",
                "vllm":      "Vérifiez que le modèle vLLM est chargé (NativeVLLMClient)",
                "ollama":    "Vérifiez qu'Ollama est démarré (`ollama serve`) et que le modèle est disponible",
            }
            hint = hints.get(backend, "Vérifiez la configuration du backend LLM")
            raise RuntimeError(
                f"Impossible de joindre le backend LLM ({backend}). "
                f"{hint}. Erreur : {exc}"
            ) from exc
        logger.debug("[%s] Plan LLM raw output: %s", state.run_id, raw[:300])

        try:
            data = _extract_json(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            logger.error("[%s] Failed to parse plan JSON: %s", state.run_id, exc)
            # Plan minimal de secours : une seule tâche vers OPNsense
            data = {
                "understanding": query,
                "objective": query,
                "tasks": [{
                    "id": "t1",
                    "name": "Exécuter la demande",
                    "description": query,
                    "agent": "opnsense",
                    "priority": "HIGH",
                    "requires_approval": False,
                }],
            }

        state.understanding = data.get("understanding", "")
        state.objective = data.get("objective", "")

        for raw_task in data.get("tasks", []):
            desc = raw_task.get("description", "")
            directive = raw_task.get("directive") or None   # null → None
            state.tasks.append(Task(
                id=raw_task.get("id", str(uuid.uuid4())[:4]),
                name=raw_task.get("name", desc[:40]),
                description=desc,
                agent=raw_task.get("agent", "opnsense"),
                priority=raw_task.get("priority", "MEDIUM"),
                requires_approval=_needs_approval(directive, desc),
                directive=directive,
                cap_args=raw_task.get("args", {}),
            ))

        logger.info(
            "[%s] Plan créé : %d tâche(s) | objectif : %s",
            state.run_id, len(state.tasks), state.objective,
        )
        return state

    async def execute_plan(self, state: PlanState) -> PlanState:
        """Exécute séquentiellement toutes les tâches PENDING."""
        state.status = RunStatus.EXECUTING

        for task in state.tasks:
            if task.status not in (TaskStatus.PENDING,):
                continue

            task.status = TaskStatus.RUNNING
            client = self._get_client(task.agent)
            logger.info("[%s] Exécution tâche %s (%s → %s): %s",
                        state.run_id, task.id, task.agent, client._base_url, task.name)

            try:
                if task.directive:
                    cap = self._build_cap(task, state.run_id)
                    judge_err = self._judge_cap(cap, task, state.run_id, step=-1)
                    if judge_err:
                        result = judge_err
                    else:
                        result = await client.execute_cap(cap)
                else:
                    result = await client.execute(task.description)
            except ToolAgentError as exc:
                task.status = TaskStatus.FAILED
                task.error_code = exc.error_code
                task.result = {"error": str(exc)}
                logger.error("[%s] Tâche %s FAILED (%s): %s", state.run_id, task.id, exc.error_code, exc)
                continue

            error_code = result.get("error_code")
            success = result.get("success", False)

            if success:
                task.status = TaskStatus.DONE
                task.result = result
                logger.info("[%s] Tâche %s DONE", state.run_id, task.id)
                continue

            # Gestion des erreurs non-critiques
            if error_code == "MISSING_ARG":
                completed = [t for t in state.tasks if t.status == TaskStatus.DONE]

                # Injection automatique de listing si uuid manquant sans listing préalable.
                # Cas typique : le planificateur a généré del_filter_rule sans get_filter_rule.
                error_msg = result.get("error", "")
                if "uuid" in error_msg.lower() and task.directive:
                    has_listing = any(
                        t.directive and t.directive.startswith("get_")
                        for t in completed
                    )
                    if not has_listing:
                        auto_task = await self._auto_list(task, state.run_id, client)
                        if auto_task:
                            completed = [auto_task] + completed

                refo = await self._reformulate(
                    task, error_msg, completed,
                    capabilities=self._capabilities,
                    partial_args=result.get("args", {}),
                )
                if refo is not None:
                    try:
                        if refo.is_structured:
                            # Bypass LLM — appel direct fonction+args résolus
                            logger.info(
                                "[%s] Reformulation structurée: %s(%s)",
                                state.run_id, refo.function, refo.args,
                            )
                            task.description = (
                                f"{refo.function}({refo.args})"
                            )
                            result2 = await client.execute_structured(
                                refo.function, refo.args
                            )
                        elif refo.is_natural:
                            # Reformulation en langage naturel — re-inférence vLLM
                            logger.info(
                                "[%s] Reformulation naturelle: %s",
                                state.run_id, refo.natural_language[:80],
                            )
                            task.description = refo.natural_language
                            result2 = await client.execute(refo.natural_language)
                        else:
                            result2 = {"success": False}

                        if result2.get("success"):
                            task.status = TaskStatus.DONE
                            task.result = result2
                            logger.info(
                                "[%s] Tâche %s DONE (après reformulation %s)",
                                state.run_id, task.id, refo.mode,
                            )
                            continue
                    except ToolAgentError:
                        pass

            task.status = TaskStatus.FAILED
            task.error_code = error_code
            task.result = result
            logger.warning("[%s] Tâche %s FAILED (%s)", state.run_id, task.id, error_code)

        return state

    async def synthesize(self, state: PlanState) -> str:
        """Génère le rapport Markdown final.

        Pour les tâches purement read-only (get_* / list_* / show_* / fetch_*),
        les données sont formatées directement sans passer par le LLM — le modèle
        n'apporte rien sur un listing et produit un laius inutile.

        Pour les mutations (ou mix lecture+mutation), le LLM génère le rapport
        habituel avec résumé, actions et état final.
        """
        state.status = RunStatus.SYNTHESIZING

        done_tasks = [t for t in state.tasks if t.status == TaskStatus.DONE]
        read_prefixes = ("get_", "list_", "show_", "fetch_")
        all_readonly = done_tasks and all(
            (t.directive or "").startswith(read_prefixes)
            for t in done_tasks
        )

        if all_readonly:
            report = self._format_read_report(state)
            logger.info("[%s] Rapport direct (read-only) (%d chars)", state.run_id, len(report))
            return report

        tasks_summary = "\n".join(
            f"- [{t.status}] {t.name} ({t.agent})"
            for t in state.tasks
        )
        results_detail = "\n".join(
            f"### {t.name}\nStatut: {t.status}\nRésultat: {json.dumps(t.result, ensure_ascii=False, indent=2)}"
            for t in state.tasks
        )

        system_prompt = self._loader.render("system")
        synthesis_prompt = self._loader.render(
            "synthesis",
            query=state.original_query,
            tasks_summary=tasks_summary,
            results_detail=results_detail,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": synthesis_prompt},
        ]

        try:
            report = await self._llm.chat(messages, max_tokens=1024)
        except Exception as exc:
            logger.error("[%s] Synthèse LLM échouée: %s", state.run_id, exc)
            report = "*(Synthèse indisponible — le backend LLM n'a pas pu être joint.)*"
        logger.info("[%s] Rapport généré (%d chars)", state.run_id, len(report))
        return report

    def _format_read_report(self, state: PlanState) -> str:
        """Formate directement les résultats read-only en Markdown lisible.

        Détecte les listes d'objets et les présente sous forme de tableau.
        Pour les objets scalaires (config, statut), affiche clé: valeur.
        """
        parts: list[str] = []

        for task in state.tasks:
            if task.status != TaskStatus.DONE or not task.result:
                continue
            result = task.result

            # Chercher la première liste dans le résultat (rules, peers, items, data…)
            data_list: list | None = None
            data_key: str = ""
            scalar_fields: dict = {}

            for k, v in result.items():
                if k in ("success", "error_code"):
                    continue
                if isinstance(v, list):
                    data_list = v
                    data_key = k
                elif isinstance(v, (str, int, float, bool)):
                    scalar_fields[k] = v

            if data_list is not None:
                parts.append(f"## {task.name}")
                if not data_list:
                    parts.append("*Aucun élément.*")
                    continue

                # Extraire les colonnes depuis le premier élément
                if isinstance(data_list[0], dict):
                    # Colonnes utiles : exclure les champs volumineux ou techniques
                    skip = {"created_at", "updated_at", "origin", "seq", "type"}
                    sample = data_list[0]
                    cols = [k for k in sample if k not in skip][:10]  # max 10 colonnes

                    header = "| " + " | ".join(cols) + " |"
                    sep    = "| " + " | ".join("---" for _ in cols) + " |"
                    parts.append(header)
                    parts.append(sep)
                    for item in data_list:
                        row = []
                        for c in cols:
                            val = item.get(c, "")
                            # Tronquer les valeurs longues
                            val_str = str(val)[:60] if val is not None else ""
                            row.append(val_str.replace("|", "\\|"))
                        parts.append("| " + " | ".join(row) + " |")
                    parts.append(f"\n*{len(data_list)} entrée(s)*")
                else:
                    # Liste de scalaires
                    for item in data_list:
                        parts.append(f"- {item}")

            elif scalar_fields:
                parts.append(f"## {task.name}")
                for k, v in scalar_fields.items():
                    parts.append(f"- **{k}** : {v}")
            else:
                # Fallback JSON brut (rare)
                parts.append(f"## {task.name}")
                parts.append(f"```json\n{json.dumps(result, ensure_ascii=False, indent=2)}\n```")

        failed = [t for t in state.tasks if t.status == TaskStatus.FAILED]
        if failed:
            parts.append("## Erreurs")
            for t in failed:
                err = (t.result or {}).get("error", "inconnue")
                parts.append(f"- **{t.name}** : {err}")

        return "\n".join(parts) if parts else "*Aucun résultat.*"

    # ------------------------------------------------------------------
    # Helpers privés
    # ------------------------------------------------------------------

    async def _execute_and_synthesize(self, state: PlanState) -> PlanState:
        state = await self.execute_plan(state)
        state.final_report = await self.synthesize(state)
        state.status = RunStatus.DONE
        return state

    async def _reformulate(
        self,
        task: Task,
        error_msg: str,
        completed_tasks: list = None,
        capabilities: dict = None,
        partial_args: dict = None,
    ) -> Optional[ReformulationResult]:
        """
        Demande au LLM de résoudre les arguments manquants après un MISSING_ARG.

        Le LLM reçoit :
        - le contexte (résultats des tâches précédentes, schéma de la fonction)
        - l'instruction de retourner du JSON avec l'un des trois modes :
            {"mode": "structured", "function": "...", "args": {...}}  → bypass LLM agent
            {"mode": "natural",    "command": "..."}                  → re-inférence vLLM
            {"mode": "impossible"}                                    → abandon

        Retourne un ReformulationResult ou None si la reformulation est impossible.
        """
        # --- Contexte : résultats des tâches déjà terminées ---
        context_block = ""
        if completed_tasks:
            parts = []
            for t in completed_tasks:
                if t.result:
                    result_text = json.dumps(t.result, ensure_ascii=False, indent=2)
                    if len(result_text) > 2000:
                        result_text = result_text[:2000] + "\n... (tronqué)"
                    parts.append(f"Tâche '{t.name}' (résultat) :\n{result_text}")
            if parts:
                context_block = (
                    "\n\nRésultats des tâches précédentes :\n\n"
                    + "\n\n---\n\n".join(parts)
                )

        # --- Schéma : trouver la fonction concernée dans les capacités ---
        func_name = None
        missing_args = []
        func_schema_block = ""
        if capabilities and error_msg:
            m = re.search(r"for (\w+):", error_msg)
            func_name = m.group(1) if m else None
            ma = re.search(r":\s*(.+)$", error_msg)
            if ma:
                missing_args = [a.strip() for a in ma.group(1).split(",")]

            if func_name:
                for agent_cap in capabilities.get("agents", []):
                    for fn in agent_cap.get("functions", []):
                        if fn.get("name") == func_name:
                            params = fn.get("parameters", {}).get("properties", {})
                            lines = [f"Schéma de la fonction '{func_name}' :"]
                            for arg in missing_args:
                                if arg in params:
                                    desc = params[arg].get("description", "")
                                    enum = params[arg].get("enum", [])
                                    enum_str = f" Valeurs possibles : {enum}" if enum else ""
                                    lines.append(f"  - {arg}: {desc}{enum_str}")
                                else:
                                    lines.append(f"  - {arg}: argument obligatoire")
                            func_schema_block = "\n\n" + "\n".join(lines)
                            break

        # --- Args partiels : déjà fournis par le vLLM, à conserver dans la reformulation ---
        partial_args = partial_args or {}
        partial_block = ""
        if partial_args:
            partial_block = (
                f"\n\nArguments déjà fournis par l'appel précédent (à conserver tels quels) :\n"
                + json.dumps(partial_args, ensure_ascii=False)
            )

        # --- Prompt : demande du JSON structuré ---
        # Exemple concret pour guider les petits modèles vers structured
        example_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        example_fn = func_name or "delete_filter_rule"
        example_structured = (
            f'{{"mode": "structured", "function": "{example_fn}", '
            f'"args": {{"uuid": "{example_uuid}"}}}}'
        )
        prompt = (
            f"Une fonction a échoué car des arguments obligatoires sont manquants.\n\n"
            f"Commande originale : {task.description}\n"
            f"Erreur : {error_msg}"
            f"{func_schema_block}"
            f"{partial_block}"
            f"{context_block}\n\n"
            f"Tu dois retourner un objet JSON (et UNIQUEMENT le JSON) avec l'un de ces formats :\n\n"
            f'1. PRÉFÉRÉ — Si les résultats ci-dessus contiennent les valeurs manquantes '
            f'(ex: un UUID dans une liste) :\n'
            f'   {example_structured}\n\n'
            f'2. Seulement si mode 1 impossible — reformulation langage naturel :\n'
            f'   {{"mode": "natural", "command": "supprime la règle firewall avec uuid=<valeur_réelle>"}}\n\n'
            f'3. Si tu ne peux absolument pas déterminer les valeurs :\n'
            f'   {{"mode": "impossible"}}\n\n'
            f"RÈGLES STRICTES :\n"
            f"- N'invente aucune valeur — utilise uniquement ce qui figure dans les résultats\n"
            f"- Mode 1 est OBLIGATOIRE si tu trouves un UUID/identifiant dans les résultats\n"
            f"- En mode structuré, inclure TOUS les arguments : ceux déjà fournis ET les nouveaux\n"
            f"- En mode natural, utilise du langage naturel (PAS de syntaxe function(arg)) :\n"
            f'  ✓ "supprime la règle firewall avec uuid=f9ed38a8-..."\n'
            f'  ✗ "delete_filter_rule f9ed38a8-..."  ← syntaxe invalide\n'
            f"- Réponds UNIQUEMENT avec le JSON, sans texte avant ni après"
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            raw = await self._llm.chat(messages, max_tokens=400)
            raw = raw.strip()
            data = _extract_json(raw)
            mode = data.get("mode")

            if mode == "structured":
                fn = data.get("function", func_name)
                args = data.get("args", {})
                if fn and args:
                    # Merger les args partiels (déjà fournis) sous les nouveaux args
                    # Les args résolus par le LLM ont priorité sur les partiels
                    merged = {**partial_args, **args}
                    logger.info("[reformulate] structured: %s(%s)", fn, merged)
                    return ReformulationResult(mode="structured", function=fn, args=merged)

            elif mode == "natural":
                cmd = data.get("command", "")
                if cmd and cmd != task.description:
                    # --- Filet de sécurité : si le modèle est retombé en mode natural
                    # alors que le résultat contient un UUID, on tente une conversion
                    # automatique vers structured (évite la confusion tool-call-id/uuid). ---
                    if func_name and missing_args:
                        uuids_found = _UUID_RE.findall(cmd)
                        uuid_args = [a for a in missing_args if "uuid" in a.lower() or a == "id"]
                        if uuids_found and len(uuid_args) <= len(uuids_found):
                            auto_args = {arg: uuids_found[i] for i, arg in enumerate(uuid_args)}
                            merged = {**partial_args, **auto_args}
                            logger.info(
                                "[reformulate] natural→structured (auto-UUID): %s(%s)",
                                func_name, merged,
                            )
                            return ReformulationResult(
                                mode="structured", function=func_name, args=merged
                            )
                    logger.info("[reformulate] natural: %s", cmd[:80])
                    return ReformulationResult(mode="natural", natural_language=cmd)

            # mode="impossible" ou non reconnu
            logger.warning("[reformulate] impossible/unrecognized for: %s", task.description[:60])
            return None

        except Exception as exc:
            logger.warning("Reformulation LLM failed: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Mode ReAct
    # ------------------------------------------------------------------

    async def react(self, query: str, max_steps: int = 10) -> PlanState:
        """
        Mode ReAct — Raisonnement + Action en boucle (alternative à run()).

        À chaque étape, le LLM voit la demande + l'historique complet des
        actions déjà exécutées, puis décide de la prochaine action ou signale
        qu'il a terminé.  Gère les checkpoints : si une action destructive est
        proposée, pause et retourne CHECKPOINT_WAIT. L'appelant reprend ensuite
        via resume_after_approval() qui délègue à _resume_react().

        Avantages par rapport à run() :
        - Peut lire des données avant d'agir (pas besoin de planner en avance)
        - Conditions sur les résultats : agit seulement si la règle existe
        - Itération sur des listes de N éléments inconnus au moment de la demande
        """
        state = PlanState.new(query)
        state.react_mode = True
        state.understanding = query
        state.objective = query
        state.status = RunStatus.EXECUTING

        try:
            caps = await self._fetch_capabilities()
            self._capabilities = caps
            self._judge.update(caps)
            caps_summary = self._summarize_capabilities(caps)
        except Exception as exc:
            logger.warning("Cannot fetch capabilities: %s", exc)
            self._capabilities = {}
            caps_summary = "opnsense (firewall), wireguard (vpn), crowdsec (idps)"

        return await self._react_loop(state, [], caps_summary, max_steps, start_step=0)

    async def _react_loop(
        self,
        state: PlanState,
        history: list,
        caps_summary: str,
        max_steps: int,
        start_step: int = 0,
    ) -> PlanState:
        """Boucle ReAct principale — partagée par react() et _resume_react()."""
        read_only = _is_read_only_query(state.original_query)
        _seen: set = set()  # (directive, args) déjà exécutés — filet de sécurité anti-boucle

        for step in range(start_step, start_step + max_steps):
            decision = await self._next_react_action(
                state.original_query, history, caps_summary, state.run_id, step,
            )

            if decision.get("done"):
                logger.info("[%s] ReAct terminé après %d étape(s)", state.run_id, step)
                break

            action_spec = decision.get("action")
            if not action_spec:
                logger.warning("[%s] ReAct: pas d'action dans la décision, arrêt", state.run_id)
                break

            thought = decision.get("thought", "")
            if thought:
                logger.debug("[%s] ReAct étape %d thought: %s", state.run_id, step + 1, thought[:300])
            task = self._action_to_task(action_spec, step + 1)
            state.tasks.append(task)

            # Checkpoint si action destructive
            if task.requires_approval:
                task.status = TaskStatus.WAITING_APPROVAL
                state.react_history = history
                state.react_pending_action = action_spec
                state.react_pending_thought = thought
                state.status = RunStatus.CHECKPOINT_WAIT
                state.checkpoint_at = time.time()
                logger.info(
                    "[%s] ReAct checkpoint étape %d: %s",
                    state.run_id, step + 1, task.directive or task.name,
                )
                return state

            # Exécuter l'action
            task.status = TaskStatus.RUNNING
            client = self._get_client(task.agent)
            logger.info("[%s] ReAct étape %d: %s", state.run_id, step + 1, task.name)

            try:
                if task.directive:
                    cap = self._build_cap(task, state.run_id)
                    judge_err = self._judge_cap(cap, task, state.run_id, step=step + 1)
                    if judge_err:
                        result = judge_err
                    else:
                        result = await client.execute_cap(cap)
                else:
                    result = await client.execute(task.description)
                task.status = TaskStatus.DONE if result.get("success") else TaskStatus.FAILED
                task.result = result
                logger.debug(
                    "[%s] ReAct étape %d résultat: %s",
                    state.run_id, step + 1, self._summarize_result(result)[:300],
                )
            except Exception as exc:
                task.status = TaskStatus.FAILED
                task.result = {"error": str(exc), "success": False}
                result = task.result
                logger.error(
                    "[%s] ReAct étape %d exception (directive=%s args=%s): %s",
                    state.run_id, step + 1, task.directive, task.cap_args, exc,
                )

            # Filet anti-boucle : même directive + mêmes args déjà exécutés → stop
            exec_key = f"{task.directive}|{json.dumps(task.cap_args, sort_keys=True)}"
            if exec_key in _seen:
                logger.warning(
                    "[%s] ReAct: directive '%s' déjà exécutée avec mêmes args — arrêt",
                    state.run_id, task.directive,
                )
                break
            _seen.add(exec_key)

            history.append({
                "step":    step + 1,
                "thought": thought,
                "action":  action_spec,
                "result":  self._summarize_result(result),
            })
            state.react_history = history

            # Sortie automatique après lecture réussie si la query est read-only
            if (read_only
                    and task.directive
                    and task.directive.startswith(_READ_PREFIXES)
                    and task.status == TaskStatus.DONE):
                logger.info("[%s] ReAct: query lecture seule — arrêt après résultat", state.run_id)
                break
            logger.info(
                "[%s] ReAct étape %d %s",
                state.run_id, step + 1,
                "OK" if task.status == TaskStatus.DONE else "FAILED",
            )

        state.final_report = await self.synthesize(state)
        state.status = RunStatus.DONE
        return state

    async def _resume_react(self, state: PlanState) -> PlanState:
        """Reprend la boucle ReAct après approbation d'un checkpoint."""
        pending_action = state.react_pending_action
        if not pending_action:
            logger.error("[%s] ReAct resume: pas d'action en attente", state.run_id)
            state.status = RunStatus.ABORTED
            return state

        # Re-fetch capabilities (le coordinateur peut avoir redémarré)
        try:
            caps = await self._fetch_capabilities()
            self._capabilities = caps
            self._judge.update(caps)
            caps_summary = self._summarize_capabilities(caps)
        except Exception:
            caps_summary = "opnsense (firewall), wireguard (vpn), crowdsec (idps)"

        # Exécuter l'action approuvée
        history = list(state.react_history or [])
        step_num = len(history) + 1
        task_id = f"r{step_num}"

        # Réutiliser la task WAITING_APPROVAL existante plutôt qu'en créer une
        # nouvelle avec le même ID. Si on ajoutait une task dupliquée, le broadcast
        # SSE final enverrait d'abord l'ancienne (checkpoint_wait) puis la nouvelle
        # (done) — côté frontend upsertTask voit brièvement l'état checkpoint_wait
        # et réaffiche les boutons d'approbation, provoquant une boucle infinie.
        task = next(
            (t for t in state.tasks if t.id == task_id and t.status == TaskStatus.WAITING_APPROVAL),
            None,
        )
        if task is None:
            # Fallback (ne devrait pas arriver en mode ReAct normal)
            task = self._action_to_task(pending_action, step_num)
            state.tasks.append(task)
        task.status = TaskStatus.RUNNING
        client = self._get_client(task.agent)

        logger.info("[%s] ReAct resume: exécution de %s", state.run_id, task.directive or task.name)

        try:
            if task.directive:
                cap = self._build_cap(task, state.run_id)
                judge_err = self._judge_cap(cap, task, state.run_id, step=-1)
                if judge_err:
                    result = judge_err
                else:
                    result = await client.execute_cap(cap)
            else:
                result = await client.execute(task.description)
            task.status = TaskStatus.DONE if result.get("success") else TaskStatus.FAILED
            task.result = result
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.result = {"error": str(exc), "success": False}
            result = task.result

        history.append({
            "step":    step_num,
            "thought": state.react_pending_thought or "",
            "action":  pending_action,
            "result":  self._summarize_result(result),
        })
        state.react_history = history
        state.react_pending_action = None
        state.react_pending_thought = None
        state.status = RunStatus.EXECUTING

        max_remaining = 10 - step_num
        if max_remaining <= 0:
            state.final_report = await self.synthesize(state)
            state.status = RunStatus.DONE
            return state

        return await self._react_loop(state, history, caps_summary, max_remaining, start_step=step_num)

    async def _next_react_action(
        self,
        query: str,
        history: list,
        caps_summary: str,
        run_id: str,
        step: int,
    ) -> dict:
        """Demande au LLM quelle est la prochaine action dans la boucle ReAct."""
        if history:
            lines = []
            for h in history:
                directive = h["action"].get("directive") or h["action"].get("description", "?")
                args = h["action"].get("args", {})
                args_str = f"({json.dumps(args, ensure_ascii=False)})" if args else "()"
                lines.append(f"\nÉtape {h['step']} — {h['thought']}")
                lines.append(f"  Action: {directive}{args_str}")
                lines.append(f"  Résultat: {h['result']}")
            history_text = "\n".join(lines)
        else:
            history_text = "Aucune action effectuée."

        prompt = self._loader.render(
            "react_step",
            query=query,
            history=history_text,
            capabilities_summary=caps_summary,
        )
        messages = [
            {"role": "system", "content": self._loader.render("system")},
            {"role": "user",   "content": prompt},
        ]
        try:
            raw = await self._llm.chat(messages, max_tokens=512)
            logger.debug("[%s] ReAct LLM (étape %d): %s", run_id, step + 1, raw[:200])
            return _extract_json(raw)
        except Exception as exc:
            logger.warning("[%s] ReAct LLM parse failed (étape %d): %s", run_id, step + 1, exc)
            return {"done": True}

    def _action_to_task(self, action_spec: dict, step_num: int) -> Task:
        """Construit un Task depuis une spécification d'action ReAct."""
        directive    = action_spec.get("directive")
        description  = action_spec.get("description") or directive or f"étape {step_num}"
        requires_approval = _needs_approval(directive, description)

        return Task(
            id=f"r{step_num}",
            name=description[:60],
            description=description,
            agent=action_spec.get("agent", "opnsense"),
            directive=directive,
            cap_args=action_spec.get("args", {}),
            priority="HIGH",
            requires_approval=requires_approval,
        )

    def _summarize_result(self, result: dict) -> str:
        """Résume un résultat d'action pour l'historique ReAct (max 4000 chars)."""
        if not result:
            return "Pas de résultat"
        if not result.get("success"):
            return f"ÉCHEC: {result.get('error', 'erreur inconnue')}"
        data = {k: v for k, v in result.items() if k not in ("success", "error_code")}
        text = json.dumps(data, ensure_ascii=False)
        if len(text) > 4000:
            text = text[:4000] + "... (tronqué)"
        return text

    async def _auto_list(
        self,
        failed_task: "Task",
        run_id: str,
        client: "ToolAgentClient",
    ) -> Optional["Task"]:
        """
        Exécute automatiquement une tâche de listing quand une mutation échoue
        sur uuid manquant et qu'aucun listing préalable n'a été effectué.

        Retourne la Task de listing (status=DONE, result rempli) si réussie, None sinon.

        Exemple : del_filter_rule sans uuid → injecte get_filter_rule, récupère la liste,
        puis la reformulation peut extraire l'UUID correspondant à la description.
        """
        listing_directive = _MUTATION_TO_LISTING.get(failed_task.directive or "")
        if not listing_directive:
            logger.debug(
                "[%s] Pas de listing connu pour directive '%s'",
                run_id, failed_task.directive,
            )
            return None

        listing_task = Task(
            id=f"{failed_task.id}_autolist",
            name=f"Listing auto ({listing_directive})",
            description=f"liste les ressources pour résoudre l'UUID manquant de '{failed_task.name}'",
            agent=failed_task.agent,
            directive=listing_directive,
            priority="HIGH",
            requires_approval=False,
            status=TaskStatus.RUNNING,
        )
        logger.info(
            "[%s] Injection auto listing '%s' (manque uuid pour '%s')",
            run_id, listing_directive, failed_task.directive,
        )
        cap = self._build_cap(listing_task, run_id)
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                res = await client.execute_cap(cap)
                if res.get("success"):
                    listing_task.status = TaskStatus.DONE
                    listing_task.result = res
                    count = len(res.get("rules") or res.get("data") or res.get("items") or [])
                    logger.info(
                        "[%s] Auto-listing '%s' → %d entrée(s)",
                        run_id, listing_directive, count,
                    )
                    return listing_task
                else:
                    logger.warning(
                        "[%s] Auto-listing '%s' retourné success=False: %s",
                        run_id, listing_directive, res.get("error", "?"),
                    )
                    return None  # erreur logique, pas la peine de retenter
            except Exception as exc:
                if attempt < max_attempts:
                    delay = 2 * attempt
                    logger.warning(
                        "[%s] Auto-listing '%s' échoué (tentative %d/%d), retry dans %ds: %s",
                        run_id, listing_directive, attempt, max_attempts, delay, exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        "[%s] Auto-listing '%s' échoué après %d tentatives: %s",
                        run_id, listing_directive, max_attempts, exc,
                    )
        return None

    def _get_client(self, agent: str) -> ToolAgentClient:
        """
        Retourne le client HTTP correspondant à l'agent demandé.

        Fallback : si l'agent n'est pas dans le registre (agent inconnu ou non
        configuré), utilise le client opnsense — évite un crash sur un plan mal
        formé. Un warning est loggé pour signaler l'incohérence.
        """
        client = self._tools.get(agent)
        if client is None:
            logger.warning("Agent '%s' non enregistré, fallback sur 'opnsense'", agent)
            client = self._tools.get("opnsense") or next(iter(self._tools.values()))
        return client

    async def _fetch_capabilities(self) -> dict:
        """
        Agrège les capacités de tous les agents enregistrés.

        Les agents injoignables sont ignorés (dégradation gracieuse) — un agent
        en panne ne bloque pas la planification sur les autres.
        """
        merged: dict = {"agents": []}
        for name, client in self._tools.items():
            try:
                caps = await client.get_capabilities()
                merged["agents"].extend(caps.get("agents", []))
            except Exception as exc:
                logger.warning("Cannot fetch capabilities from %s: %s", name, exc)
        return merged

    def _build_cap(self, task: Task, run_id: str) -> CoordinatorDirective:
        """
        Construit un paquet CAP v1 à partir d'une tâche planifiée.

        - Extrait les entités NER depuis task.description via AnonyNER
        - Fusionne avec les args discrets task.cap_args (action, protocol, uuid…)
        - Ajoute le contexte de traçabilité (run_id, task_id)

        Si AnonyNER n'est pas disponible, entities restera vide — le SLM agent
        devra inférer les valeurs depuis l'historique ou retourner MISSING_ARG.
        """
        entities = self._ner.extract(task.description)
        return CoordinatorDirective(
            directive=task.directive,
            entities=entities,
            args=task.cap_args,
            context={
                "source":  "coordinator",
                "run_id":  run_id,
                "task_id": task.id,
            },
        )

    def _judge_cap(self, cap: CoordinatorDirective, task: Task, run_id: str, step: int) -> Optional[dict]:
        """
        Valide un paquet CAP avant exécution via CAPValidator.

        Retourne None si le paquet est valide, ou un dict résultat d'erreur
        (format compatible TaskResult) si la validation échoue.

        Le step est utilisé uniquement pour le logging (-1 = mode plan classique).
        """
        verdict = self._judge.validate(cap, task.agent)
        if verdict.passed:
            return None
        step_label = f"étape {step}" if step >= 0 else "plan"
        logger.warning(
            "[%s] JudgeAgent %s REJECTED directive=%s : %s",
            run_id, step_label, cap.directive, verdict.reason,
        )
        return verdict.to_error_result()

    def _summarize_capabilities(self, caps: dict) -> str:
        """
        Résume les capacités pour le prompt de planification.

        Format enrichi par rapport à la liste brute de noms :
        - LECTURE  : noms uniquement (compacts, connus du modèle)
        - MUTATION : signature(args requis) + [PRÉCONDITION: get_xxx] + [DESTRUCTIF]

        Contrainte de taille : max MAX_WRITE_PER_AGENT lignes de mutation par agent
        pour tenir dans les ~800 tokens disponibles du contexte de planification.
        """
        _TYPE_SHORT = {"string": "str", "integer": "int", "boolean": "bool", "array": "list"}
        MAX_WRITE_PER_AGENT = 30

        lines = []
        for agent in caps.get("agents", []):
            agent_name = agent.get("name", "?")
            funcs = agent.get("functions", [])

            read_names: list[str] = []
            write_lines: list[str] = []

            for fn in funcs:
                fn_name = fn.get("name", "")
                params   = fn.get("parameters", {})
                required = params.get("required", [])
                props    = params.get("properties", {})

                # Fonctions de lecture → liste compacte
                if fn_name.startswith(("get_", "list_", "show_", "fetch_")):
                    read_names.append(fn_name)
                    continue

                # Signature : func(arg: type, …)
                sig_parts = []
                for arg in required:
                    raw_type = props.get(arg, {}).get("type", "string")
                    sig_parts.append(f"{arg}: {_TYPE_SHORT.get(raw_type, raw_type)}")
                sig = f"{fn_name}({', '.join(sig_parts)})"

                # Description courte (première ligne du docstring)
                fn_desc = fn.get("description", "")
                desc_str = f" — {fn_desc}" if fn_desc else ""

                # Flags
                flags: list[str] = []
                if fn_name in _MUTATION_TO_LISTING:
                    flags.append(f"[PRÉCONDITION: {_MUTATION_TO_LISTING[fn_name]}]")
                # Seules les opérations réellement irréversibles ou disruptives
                # sont marquées DESTRUCTIF — add_/create_/update_/enable_ ne le sont pas.
                if fn_name.startswith(("del_", "delete_", "disable_", "block_", "toggle_")) or is_destructive(fn_name):
                    flags.append("[DESTRUCTIF]")

                flag_str = "  " + " ".join(flags) if flags else ""
                write_lines.append(f"    {sig}{desc_str}{flag_str}")

            lines.append(f"- {agent_name}:")
            if read_names:
                lines.append(f"    LECTURE : {', '.join(read_names)}")
            for wl in write_lines[:MAX_WRITE_PER_AGENT]:
                lines.append(wl)
            if len(write_lines) > MAX_WRITE_PER_AGENT:
                lines.append(f"    … +{len(write_lines) - MAX_WRITE_PER_AGENT} autres mutations")

        return "\n".join(lines) if lines else "opnsense, wireguard, crowdsec"
