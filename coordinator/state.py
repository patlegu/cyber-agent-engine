"""
coordinator/state.py — Modèles d'état du coordinateur.

PlanState représente une exécution complète : plan → tâches → rapport.
CheckpointStore gère la persistance en mémoire des états en attente d'approbation.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    PENDING          = "pending"
    RUNNING          = "running"
    DONE             = "done"
    FAILED           = "failed"
    WAITING_APPROVAL = "waiting_approval"
    REJECTED         = "rejected"


class RunStatus(str, Enum):
    PLANNING         = "planning"
    EXECUTING        = "executing"
    CHECKPOINT_WAIT  = "checkpoint_wait"
    SYNTHESIZING     = "synthesizing"
    DONE             = "done"
    ABORTED          = "aborted"


# ---------------------------------------------------------------------------
# Heuristique "action destructive"
# ---------------------------------------------------------------------------

_DESTRUCTIVE_KEYWORDS = [
    # English
    "delete", "remove", "ban", "block", "disable", "drop", "flush", "purge", "reset",
    # French
    "supprim", "efface", "désactiv", "desactiv", "bannir", "bloqu", "vider", "réinitialis",
]


def is_destructive(description: str) -> bool:
    """Retourne True si la description semble être une action destructive."""
    lower = description.lower()
    return any(kw in lower for kw in _DESTRUCTIVE_KEYWORDS)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """Représente une sous-tâche à déléguer à un agent-outil."""
    id: str
    name: str
    description: str        # Commande en langage naturel (fallback si pas de directive)
    agent: str              # "opnsense" | "wireguard" | "crowdsec"
    priority: str           # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[dict] = None
    error_code: Optional[str] = None
    requires_approval: bool = False
    approved: Optional[bool] = None  # None=en attente, True=ok, False=rejeté

    # --- CAP v1 (Coordinator-Agent Packet) ---
    # Remplis par le LLM de planification quand il peut résoudre la fonction cible.
    # Si directive est None, execute_plan() utilise le mode NL (fallback).
    directive: Optional[str] = None     # Nom de fonction exact (snake_case), ex: "block_ip"
    cap_args: dict = field(default_factory=dict)  # Params non-NER résolus : action, protocol, etc.

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "agent": self.agent,
            "priority": self.priority,
            "status": self.status,
            "result": self.result,
            "error_code": self.error_code,
            "requires_approval": self.requires_approval,
            "approved": self.approved,
        }
        if self.directive:
            d["directive"] = self.directive
        if self.cap_args:
            d["cap_args"] = self.cap_args
        return d


@dataclass
class PlanState:
    """État complet d'une exécution du coordinateur."""
    run_id: str
    original_query: str
    understanding: str
    objective: str
    tasks: List[Task] = field(default_factory=list)
    status: RunStatus = RunStatus.PLANNING
    final_report: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    # --- Mode ReAct (reasoning + acting en boucle) ---
    # Activé quand PilotAgent.react() est utilisé à la place de run().
    react_mode: bool = False
    # Historique des étapes : [{"step": int, "thought": str, "action": dict, "result": str}, ...]
    react_history: List[dict] = field(default_factory=list)
    # Action destructive en attente d'approbation (checkpoint)
    react_pending_action: Optional[dict] = None
    react_pending_thought: Optional[str] = None
    checkpoint_at: Optional[float] = None  # timestamp CHECKPOINT_WAIT, pour expiration auto

    @classmethod
    def new(cls, query: str) -> "PlanState":
        return cls(
            run_id=str(uuid.uuid4())[:8],
            original_query=query,
            understanding="",
            objective="",
        )

    def pending_approvals(self) -> List[Task]:
        return [t for t in self.tasks if t.status == TaskStatus.WAITING_APPROVAL]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "original_query": self.original_query,
            "understanding": self.understanding,
            "objective": self.objective,
            "status": self.status,
            "tasks": [t.to_dict() for t in self.tasks],
            "final_report": self.final_report,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# CheckpointStore — persistance en mémoire
# ---------------------------------------------------------------------------

class CheckpointStore:
    """
    Stockage en mémoire des PlanState.
    Suffisant pour une instance unique ; remplaçable par Redis sans changer l'interface.
    """

    def __init__(self):
        self._store: Dict[str, PlanState] = {}

    def save(self, state: PlanState) -> None:
        self._store[state.run_id] = state

    def get(self, run_id: str) -> Optional[PlanState]:
        return self._store.get(run_id)

    def all(self) -> List[PlanState]:
        return list(self._store.values())

    def list_pending_approvals(self) -> List[PlanState]:
        return [s for s in self._store.values() if s.status == RunStatus.CHECKPOINT_WAIT]
