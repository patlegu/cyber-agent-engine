"""
coordinator/server.py — API FastAPI du coordinateur (port 3001).

Authentification :
  Toutes les routes (sauf /health) exigent le header HTTP :
    X-API-Key: <valeur de COORDINATOR_API_KEY dans le .env>

  Si COORDINATOR_API_KEY n'est pas définie au démarrage, le serveur logue un
  avertissement et passe en mode dev (accès libre). Ne jamais déployer sans clé.

Variables d'environnement :
  COORDINATOR_API_KEY   Clé secrète que les clients doivent présenter (obligatoire en prod)
  TOOL_AGENT_URL        URL du tool-agent OPNsense  (défaut : http://localhost:3000)
  TOOL_AGENT_KEY        Clé API de l'agent OPNsense (transmise en interne)
  WIREGUARD_AGENT_URL   URL du tool-agent WireGuard  (défaut : http://localhost:3001)
  WIREGUARD_AGENT_KEY   Clé API de l'agent WireGuard
  CROWDSEC_AGENT_URL    URL du tool-agent CrowdSec   (défaut : http://localhost:3002)
  CROWDSEC_AGENT_KEY    Clé API de l'agent CrowdSec

Routes :
  POST /coordinator/execute              → Lance un plan
  GET  /coordinator/status/{run_id}      → État d'un plan
  GET  /coordinator/checkpoint/{run_id}  → Tâches en attente d'approbation
  POST /coordinator/checkpoint/{run_id}/approve → Approuver et reprendre
  POST /coordinator/checkpoint/{run_id}/reject  → Abandonner
  GET  /coordinator/capabilities                → Proxy vers tool-agent-server
  GET  /coordinator/health                      → Liveness check (pas d'auth)
"""

import asyncio
import json
import logging
import os
import signal
import threading
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

# load_dotenv() MUST run before local imports so that module-level os.getenv()
# calls in coordinator_llm.py (and siblings) read the correct values.
from dotenv import load_dotenv
load_dotenv()

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from .clients.tool_agent_client import ToolAgentClient
from .llm.coordinator_llm import CoordinatorLLM
from .pilot import PilotAgent
from .state import CheckpointStore, RunStatus, TaskStatus

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Clé que les clients externes (UI, scripts) doivent envoyer dans le header
# X-API-Key pour accéder au coordinateur.
# Si absente → mode dev (avertissement au démarrage, accès libre).
COORDINATOR_API_KEY   = os.getenv("COORDINATOR_API_KEY",   "")
DASHBOARD_TOKEN       = os.getenv("DASHBOARD_TOKEN",       "")
CHECKPOINT_TIMEOUT    = int(os.getenv("CHECKPOINT_TIMEOUT", "300"))  # secondes avant auto-rejet

# URLs et clés des tool-agent-servers spécialisés.
# TOOL_AGENT_URL est conservé comme alias rétro-compatible pour OPNsense.
OPNSENSE_AGENT_URL    = os.getenv("TOOL_AGENT_URL",         "http://localhost:3000")
OPNSENSE_AGENT_KEY    = os.getenv("TOOL_AGENT_KEY",         "")
OPNSENSE_AGENT_SOCK   = os.getenv("OPNSENSE_AGENT_SOCK",    "")  # UDS : /run/agents/opnsense.sock
WIREGUARD_AGENT_URL   = os.getenv("WIREGUARD_AGENT_URL",    "http://localhost:3001")
WIREGUARD_AGENT_KEY   = os.getenv("WIREGUARD_AGENT_KEY",    "")
WIREGUARD_AGENT_SOCK  = os.getenv("WIREGUARD_AGENT_SOCK",   "")  # UDS : /run/agents/wireguard.sock
CROWDSEC_AGENT_URL    = os.getenv("CROWDSEC_AGENT_URL",     "http://localhost:3002")
CROWDSEC_AGENT_KEY    = os.getenv("CROWDSEC_AGENT_KEY",     "")
CROWDSEC_AGENT_SOCK   = os.getenv("CROWDSEC_AGENT_SOCK",    "")  # UDS : /run/agents/crowdsec.sock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("coordinator")

# ---------------------------------------------------------------------------
# Ring-buffer log handler — alimente le endpoint GET /api/logs
# ---------------------------------------------------------------------------

_log_buffer: deque = deque(maxlen=500)
_log_lock = threading.Lock()


class _BufferLogHandler(logging.Handler):
    """Capture les logs applicatifs dans un ring-buffer (taille 500)."""

    _IGNORE_PREFIXES = ("vllm.", "torch.", "httpx.", "uvicorn.access")

    def emit(self, record: logging.LogRecord) -> None:
        if any(record.name.startswith(p) for p in self._IGNORE_PREFIXES):
            return
        try:
            entry = {
                "ts":     record.created,
                "level":  record.levelname,
                "logger": record.name,
                "msg":    self.format(record),
            }
            with _log_lock:
                _log_buffer.append(entry)
        except Exception:
            pass


_buf_handler = _BufferLogHandler()
_buf_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(_buf_handler)

# ---------------------------------------------------------------------------
# Authentification — header X-API-Key
# ---------------------------------------------------------------------------

# FastAPI lit automatiquement le header "X-API-Key" sur chaque requête.
# auto_error=False : on gère nous-mêmes le cas clé absente/invalide
# pour renvoyer un message d'erreur détaillé.
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    request: Request,
    key: Optional[str] = Depends(_api_key_header),
) -> None:
    """
    Dépendance FastAPI injectée sur toutes les routes protégées.

    Accepte deux mécanismes d'authentification :
    - X-API-Key: <COORDINATOR_API_KEY>        (clients API, scripts)
    - Authorization: Bearer <DASHBOARD_TOKEN>  (dashboard web)

    Comportement :
    - Aucune clé configurée → mode dev, accès libre (log avertissement)
    - Clé absente ou incorrecte → HTTP 401 UNAUTHORIZED
    """
    if not COORDINATOR_API_KEY and not DASHBOARD_TOKEN:
        return
    # X-API-Key (COORDINATOR_API_KEY)
    if COORDINATOR_API_KEY and key == COORDINATOR_API_KEY:
        return
    # Authorization: Bearer (DASHBOARD_TOKEN)
    if DASHBOARD_TOKEN:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and auth_header[7:] == DASHBOARD_TOKEN:
            return
    raise HTTPException(
        status_code=401,
        detail={
            "error": "UNAUTHORIZED",
            "message": "Clé API manquante ou invalide. "
                       "Ajoutez le header X-API-Key avec la valeur de COORDINATOR_API_KEY.",
        },
    )


# ---------------------------------------------------------------------------
# Global singletons
# ---------------------------------------------------------------------------
_llm: Optional[CoordinatorLLM] = None
_tool_clients: dict[str, ToolAgentClient] = {}   # clé = nom d'agent ("opnsense", …)
_store = CheckpointStore()


# ---------------------------------------------------------------------------
# Lifespan — initialisation et arrêt propre
# ---------------------------------------------------------------------------
async def _checkpoint_watchdog() -> None:
    """Rejette automatiquement les checkpoints expirés (CHECKPOINT_TIMEOUT secondes)."""
    import time
    while True:
        await asyncio.sleep(30)
        now = time.time()
        for state in _store.list_pending_approvals():
            if state.checkpoint_at and (now - state.checkpoint_at) > CHECKPOINT_TIMEOUT:
                logger.warning(
                    "[%s] Checkpoint expiré après %ds — rejet automatique",
                    state.run_id, CHECKPOINT_TIMEOUT,
                )
                for t in state.tasks:
                    if t.status == TaskStatus.WAITING_APPROVAL:
                        t.approved = False
                        t.status = TaskStatus.REJECTED
                state.status = RunStatus.ABORTED
                state.final_report = (
                    f"Plan avorté automatiquement : aucune approbation reçue "
                    f"sous {CHECKPOINT_TIMEOUT}s."
                )
                _store.save(state)
                await _broadcast({"type": "run_aborted", "run_id": state.run_id, "reason": "timeout"})


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _llm, _tool_clients
    logger.info("Starting Coordinator Server…")

    if not COORDINATOR_API_KEY:
        logger.warning(
            "COORDINATOR_API_KEY non configurée — le coordinateur est accessible "
            "sans authentification (mode dev). Définissez la variable en production."
        )
    else:
        logger.info("Authentification activée (X-API-Key)")

    _llm = CoordinatorLLM()
    await _llm.init()

    # Initialise un client HTTP par agent spécialisé
    _agent_configs = {
        "opnsense":  (OPNSENSE_AGENT_URL,  OPNSENSE_AGENT_KEY,  OPNSENSE_AGENT_SOCK),
        "wireguard": (WIREGUARD_AGENT_URL, WIREGUARD_AGENT_KEY, WIREGUARD_AGENT_SOCK),
        "crowdsec":  (CROWDSEC_AGENT_URL,  CROWDSEC_AGENT_KEY,  CROWDSEC_AGENT_SOCK),
    }
    for name, (url, key, sock) in _agent_configs.items():
        client = ToolAgentClient(base_url=url, api_key=key, socket_path=sock)
        await client.__aenter__()
        _tool_clients[name] = client
        transport = f"UDS:{sock}" if sock else url
        logger.info("Agent client ready: %s → %s", name, transport)

    watchdog = asyncio.create_task(_checkpoint_watchdog())
    logger.info("Checkpoint watchdog démarré (timeout=%ds)", CHECKPOINT_TIMEOUT)

    yield

    watchdog.cancel()
    logger.info("Shutting down Coordinator…")
    # Débloquer toutes les connexions SSE en envoyant un sentinel None.
    # Sans ça, les StreamingResponse restent bloquées sur q.get(timeout=15s)
    # et uvicorn attend indéfiniment la fermeture des connexions.
    for q in list(_sse_queues):
        try:
            q.put_nowait(None)
        except asyncio.QueueFull:
            pass
    for client in _tool_clients.values():
        await client.__aexit__(None, None, None)
    _tool_clients.clear()
    await _llm.shutdown()


app = FastAPI(title="Cyber Coordinator", version="1.0", lifespan=lifespan)

# CORS — autorise le frontend (Vite :5173 ou dashboard :8080) à appeler le coordinateur
# directement. Configurable via CORS_ORIGINS dans .env.
_CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:8080,http://127.0.0.1:5173,http://127.0.0.1:8080",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Modèles Pydantic (validation automatique des corps de requête)
# ---------------------------------------------------------------------------

class ExecuteRequest(BaseModel):
    query: str                  # Demande en langage naturel (ex: "bloque toutes les IPs chinoises")
    context: Dict[str, Any] = {}  # Contexte optionnel transmis au pilot


class ApproveRequest(BaseModel):
    comment: str = ""           # Commentaire libre de l'opérateur (traçabilité)


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

def _make_pilot() -> PilotAgent:
    """Crée une instance PilotAgent à partir des singletons globaux."""
    return PilotAgent(tool_clients=_tool_clients, llm=_llm)


def _serialize_state(state) -> dict:
    d = state.to_dict()
    # Ajouter les tâches en attente pour les réponses checkpoint_wait
    d["pending_tasks"] = [t.to_dict() for t in state.pending_approvals()]
    return d


# ---------------------------------------------------------------------------
# Routes — toutes protégées par verify_api_key sauf /health
# ---------------------------------------------------------------------------

@app.post("/coordinator/execute", dependencies=[Depends(verify_api_key)])
async def execute(req: ExecuteRequest, background_tasks: BackgroundTasks):
    """
    Lance l'exécution d'une demande haut niveau.

    Flux :
    1. Le PilotAgent génère un plan JSON (via le LLM coordinateur).
    2. Chaque tâche du plan est déléguée à l'agent spécialiste (opnsense / wireguard / crowdsec).
    3. Si une tâche est marquée destructive (requires_approval=True) →
         retourne HTTP 202 avec status=checkpoint_wait et les URLs approve/reject.
    4. Sinon → retourne le rapport final directement (peut prendre plusieurs secondes).

    Erreurs :
    - 503 si le backend LLM est inaccessible.
    - 401 si la clé API est manquante ou invalide.
    """
    pilot = _make_pilot()
    try:
        state = await pilot.react(req.query)
    except Exception as exc:
        logger.exception("Erreur non gérée dans pilot.react()")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "COORDINATOR_ERROR",
                "message": str(exc),
                "hint": "Vérifiez que le backend LLM (Ollama/vLLM) est démarré.",
            },
        ) from exc
    _store.save(state)

    if state.status == RunStatus.CHECKPOINT_WAIT:
        return JSONResponse(
            status_code=202,
            content={
                "status": "checkpoint_wait",
                "run_id": state.run_id,
                "message": "Des actions destructives nécessitent une approbation humaine.",
                "pending_tasks": [t.to_dict() for t in state.pending_approvals()],
                "approve_url": f"/coordinator/checkpoint/{state.run_id}/approve",
                "reject_url":  f"/coordinator/checkpoint/{state.run_id}/reject",
            },
        )

    return {
        "status": "done",
        "run_id": state.run_id,
        "objective": state.objective,
        "report": state.final_report,
        "tasks": [t.to_dict() for t in state.tasks],
    }


@app.get("/coordinator/status/{run_id}", dependencies=[Depends(verify_api_key)])
async def get_status(run_id: str):
    """
    Retourne l'état complet d'un plan identifié par son run_id.

    Utile pour poller l'avancement après un approve (exécution en arrière-plan).
    """
    state = _store.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return _serialize_state(state)


@app.get("/coordinator/checkpoint/{run_id}", dependencies=[Depends(verify_api_key)])
async def get_checkpoint(run_id: str):
    """
    Retourne les tâches en attente d'approbation humaine pour un plan donné.

    N'est valide que si le plan est en status=checkpoint_wait (HTTP 409 sinon).
    """
    state = _store.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if state.status != RunStatus.CHECKPOINT_WAIT:
        raise HTTPException(
            status_code=409,
            detail=f"Run '{run_id}' is not in checkpoint_wait (status: {state.status})",
        )
    return {
        "run_id": run_id,
        "objective": state.objective,
        "pending_tasks": [t.to_dict() for t in state.pending_approvals()],
    }


@app.post("/coordinator/checkpoint/{run_id}/approve", dependencies=[Depends(verify_api_key)])
async def approve_checkpoint(run_id: str, req: ApproveRequest, background_tasks: BackgroundTasks):
    """
    Approuve toutes les tâches destructives en attente et reprend l'exécution.

    L'exécution est relancée en arrière-plan — la réponse est immédiate (HTTP 202).
    Poller GET /coordinator/status/{run_id} pour suivre l'avancement.
    """
    state = _store.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if state.status != RunStatus.CHECKPOINT_WAIT:
        raise HTTPException(status_code=409, detail="Run is not waiting for approval")

    # Marquer toutes les tâches en attente comme approuvées et verrouiller le
    # statut immédiatement — évite qu'un double-clic passe le guard ci-dessus et
    # schedule deux _resume() en parallèle sur le même état.
    for t in state.tasks:
        if t.status == TaskStatus.WAITING_APPROVAL:
            t.approved = True
    state.status = RunStatus.EXECUTING

    async def _resume():
        pilot = _make_pilot()
        await _broadcast({"type": "notification", "message": "Exécution reprise après approbation…", "status": "info"})
        try:
            updated = await pilot.resume_after_approval(state)
        except Exception as exc:
            logger.exception("[%s] Erreur dans _resume() après approbation", run_id)
            state.status = RunStatus.ABORTED
            _store.save(state)
            await _broadcast({"type": "notification", "message": f"Erreur lors de la reprise : {exc}", "status": "error"})
            # Mettre à jour les tâches bloquées en FAILED pour que le frontend
            # ne reste pas en checkpoint_wait indéfiniment.
            for t in state.tasks:
                if t.status in (TaskStatus.WAITING_APPROVAL, TaskStatus.RUNNING):
                    t.status = TaskStatus.FAILED
                    await _broadcast(_task_to_sse(t, run_id=run_id))
            return
        _store.save(updated)
        logger.info("[%s] Resumed after approval → status: %s", run_id, updated.status)
        for task in updated.tasks:
            await _broadcast(_task_to_sse(task, run_id=run_id))
        status_val = updated.status.value if hasattr(updated.status, "value") else str(updated.status)
        if status_val == "done":
            await _broadcast({"type": "notification", "message": updated.final_report or "Exécution terminée.", "status": "success"})
        else:
            await _broadcast({"type": "notification", "message": f"Exécution terminée avec statut : {status_val}", "status": "error"})

    background_tasks.add_task(_resume)

    return JSONResponse(
        status_code=202,
        content={
            "status": "resuming",
            "run_id": run_id,
            "message": "Exécution reprise en arrière-plan.",
            "status_url": f"/coordinator/status/{run_id}",
        },
    )


@app.post("/coordinator/checkpoint/{run_id}/reject", dependencies=[Depends(verify_api_key)])
async def reject_checkpoint(run_id: str):
    """
    Rejette les actions destructives en attente et avorte le plan.

    Aucune action n'est exécutée sur l'infrastructure. Le plan passe en status=aborted.
    """
    state = _store.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if state.status != RunStatus.CHECKPOINT_WAIT:
        raise HTTPException(status_code=409, detail="Run is not waiting for approval")

    for t in state.tasks:
        if t.status == TaskStatus.WAITING_APPROVAL:
            t.approved = False
            t.status = TaskStatus.REJECTED

    state.status = RunStatus.ABORTED
    state.final_report = "Plan avorté par l'opérateur humain avant l'exécution des actions destructives."
    _store.save(state)

    return {
        "status": "aborted",
        "run_id": run_id,
        "message": "Plan avorté. Aucune action destructive n'a été exécutée.",
    }


@app.get("/coordinator/capabilities", dependencies=[Depends(verify_api_key)])
async def get_capabilities():
    """
    Agrège les capacités de tous les tool-agent-servers.

    Retourne la liste fusionnée des agents disponibles et leurs fonctions.
    Les agents injoignables sont ignorés (dégradation gracieuse).
    """
    merged: dict = {"agents": []}
    for name, client in _tool_clients.items():
        try:
            caps = await client.get_capabilities()
            merged["agents"].extend(caps.get("agents", []))
        except Exception as exc:
            logger.warning("Cannot fetch capabilities from %s: %s", name, exc)
    if not merged["agents"]:
        raise HTTPException(status_code=502, detail="Aucun tool-agent-server disponible")
    return merged


@app.get("/coordinator/health")
async def health():
    """
    Liveness check — pas d'authentification requise.

    Utilisé par les load-balancers et les scripts de supervision pour vérifier
    que le serveur répond. Ne retourne pas d'informations sensibles.
    """
    return {
        "status": "ok",
        "agents": {name: client._base_url for name, client in _tool_clients.items()},
    }



# ---------------------------------------------------------------------------
# Dashboard API — interface simplifiée pour le frontend web
# ---------------------------------------------------------------------------

_sse_queues: Set[asyncio.Queue] = set()


class DashboardCommandRequest(BaseModel):
    command: str


async def _broadcast(event: dict) -> None:
    """Publie un événement SSE vers tous les clients connectés au dashboard."""
    payload = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    for q in list(_sse_queues):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


def _task_to_sse(task, run_id: str = "") -> dict:
    """Convertit un Task en payload SSE compatible avec le frontend."""
    status_map = {
        "pending":          "pending",
        "running":          "running",
        "done":             "done",
        "failed":           "error",
        "waiting_approval": "checkpoint_wait",
        "rejected":         "error",
    }
    result_str = None
    if task.result:
        result_str = task.result.get("output") or str(task.result)
    payload: dict = {
        "id":          task.id,
        "agent":       task.agent,
        "description": task.description,
        "status":      status_map.get(str(task.status.value), "pending"),
        "result":      result_str,
        "created_at":  datetime.now(timezone.utc).isoformat(),
    }
    if run_id:
        payload["run_id"] = run_id
    return {"type": "task_update", "task": payload}


@app.post("/api/command")
async def api_command(req: DashboardCommandRequest):
    """
    Interface simplifiée pour le frontend web (ChatView).

    Reçoit une commande en langage naturel, exécute le plan via PilotAgent,
    publie les mises à jour de tâches en SSE, et retourne la réponse finale.
    """
    pilot = _make_pilot()
    await _broadcast({"type": "notification", "message": "Traitement en cours…", "status": "info"})

    try:
        state = await pilot.react(req.command)
    except Exception as exc:
        logger.exception("Erreur dans api_command")
        await _broadcast({"type": "notification", "message": f"Erreur : {exc}", "status": "error"})
        return {"reply": f"Erreur lors de l'exécution : {exc}"}

    _store.save(state)

    for task in state.tasks:
        await _broadcast(_task_to_sse(task, run_id=state.run_id))

    if state.status.value == "checkpoint_wait":
        reply = (
            f"Des actions destructives nécessitent une approbation humaine.\n"
            f"Utilisez les boutons Approuver / Rejeter dans l'interface."
        )
    else:
        reply = state.final_report or "Exécution terminée."

    await _broadcast({"type": "notification", "message": "Exécution terminée.", "status": "success"})
    return {"reply": reply}


@app.get("/events")
async def dashboard_events(request: Request):
    """
    Stream SSE vers le frontend dashboard.

    Publie :
    - pings toutes les 15s (maintien connexion)
    - task_update après chaque /api/command
    - notification (info / success / error)
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_queues.add(q)

    async def stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    if payload is None:  # sentinel d'arrêt propre (shutdown)
                        break
                    yield payload
                except asyncio.TimeoutError:
                    yield 'data: {"type": "ping"}\n\n'
                except asyncio.CancelledError:
                    break  # shutdown uvicorn — sortie propre sans traceback
        finally:
            _sse_queues.discard(q)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/logs")
async def get_logs(since: float = 0.0) -> Dict[str, List[dict]]:
    """
    Retourne les entrées de log récentes (ring-buffer de 500 lignes).

    Paramètre :
      since (float) — timestamp UNIX en secondes ; seules les entrées
                       postérieures à cette valeur sont retournées.
                       0.0 (défaut) → tout le buffer.

    Utilisé par le LogView Svelte pour le polling toutes les 2 s.
    """
    with _log_lock:
        entries = [e for e in _log_buffer if e["ts"] > since]
    return {"logs": entries}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import signal
    import uvicorn
    config = uvicorn.Config(
        "coordinator.server:app",
        host="0.0.0.0",
        port=3001,
        reload=False,
        timeout_graceful_shutdown=30,
    )
    server = uvicorn.Server(config)

    # Intercept SIGINT/SIGTERM before uvicorn installs its own handlers.
    # Setting server.should_exit triggers uvicorn's graceful shutdown path
    # (lifespan __aexit__ → _llm.shutdown() → del llm → EngineCore stops via IPC).
    server.install_signal_handlers = lambda: None

    def _handle_exit(signum, frame):
        # uvicorn's capture_signals() saves our handler, installs its own, then
        # restores ours and re-raises the signal after shutdown completes.
        # Ignore that re-raise — the server is already done at that point.
        if server.should_exit:
            return
        logger.info("Signal %d received — graceful shutdown… (press again to force quit)", signum)
        server.should_exit = True
        # Fermer immédiatement les connexions SSE pour débloquer uvicorn —
        # le teardown du lifespan arrive trop tard (après fermeture des connexions).
        for q in list(_sse_queues):
            try:
                q.put_nowait(None)
            except Exception:
                pass
        # Restore default handlers: a second CTRL+C will kill immediately.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)

    print("Coordinator starting on http://0.0.0.0:3001")
    server.run()
