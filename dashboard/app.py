import os
import asyncio
import json
from pathlib import Path
import psutil
import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Cyber Agent Dashboard")

# --- Authentification ---
# Si DASHBOARD_TOKEN n'est pas défini, l'auth est désactivée (mode dev).
_DASHBOARD_TOKEN: str | None = os.getenv("DASHBOARD_TOKEN")
_bearer = HTTPBearer(auto_error=False)


def require_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(default=None),  # fallback query param pour EventSource
) -> None:
    if not _DASHBOARD_TOKEN:
        return
    provided = (creds.credentials if creds else None) or token
    if provided != _DASHBOARD_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide")

STATIC_DIR = Path(__file__).parent / "static"

# Configuration
OPNSENSE_URL = os.getenv("OPNSENSE_URL", "https://192.168.1.1")
OPNSENSE_KEY = os.getenv("OPNSENSE_API_KEY")
OPNSENSE_SECRET = os.getenv("OPNSENSE_API_SECRET")
VLLM_PORT = 8000

class SystemStats(BaseModel):
    cpu_percent: float
    memory_percent: float
    disk_percent: float

class NetworkStats(BaseModel):
    internet: bool
    opnsense: bool
    opnsense_details: str = ""

class AgentStats(BaseModel):
    vllm_status: bool
    model_loaded: bool

class DashboardStatus(BaseModel):
    system: SystemStats
    network: NetworkStats
    agent: AgentStats

class CommandRequest(BaseModel):
    command: str

# --- Routes API ---

@app.get("/api/status", response_model=DashboardStatus)
async def get_status():
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent

    internet = False
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get("https://1.1.1.1")
            if resp.status_code == 200:
                internet = True
    except:
        pass

    opnsense = False
    opnsense_det = "Unreachable"
    if OPNSENSE_KEY and OPNSENSE_SECRET:
        try:
            async with httpx.AsyncClient(verify=False, timeout=2.0) as client:
                resp = await client.get(
                    f"{OPNSENSE_URL}/api/core/system/status",
                    auth=(OPNSENSE_KEY, OPNSENSE_SECRET)
                )
                if resp.status_code == 200:
                    opnsense = True
                    opnsense_det = "Online (Authenticated)"
                elif resp.status_code == 401:
                    opnsense_det = "Online (Auth Failed)"
                else:
                    opnsense_det = f"Error {resp.status_code}"
        except Exception as e:
            opnsense_det = f"Connection Error: {str(e)}"
    else:
        opnsense = True
        opnsense_det = "Simulation Mode"

    vllm_ok = False
    try:
        async with httpx.AsyncClient(timeout=0.5) as client:
            resp = await client.get(f"http://localhost:{VLLM_PORT}/health")
            if resp.status_code == 200:
                vllm_ok = True
    except:
        pass

    return {
        "system": {"cpu_percent": cpu, "memory_percent": mem, "disk_percent": disk},
        "network": {"internet": internet, "opnsense": opnsense, "opnsense_details": opnsense_det},
        "agent": {"vllm_status": vllm_ok, "model_loaded": True},
    }


@app.post("/api/command", dependencies=[Depends(require_auth)])
async def command(req: CommandRequest):
    """
    Délégation de la commande au coordinateur (port 3001).
    """
    coordinator_url = os.getenv("COORDINATOR_URL", "http://localhost:3001")
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(f"{coordinator_url}/api/command", json={"command": req.command})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"reply": f"Erreur de communication avec le coordinateur : {e}"}


@app.post("/coordinator/checkpoint/{run_id}/approve", dependencies=[Depends(require_auth)])
async def approve_checkpoint(run_id: str):
    """Relaie l'approbation d'un checkpoint au coordinateur."""
    coordinator_url = os.getenv("COORDINATOR_URL", "http://localhost:3001")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                f"{coordinator_url}/coordinator/checkpoint/{run_id}/approve",
                json={"comment": "Approuvé via dashboard"},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"Erreur coordinateur : {e}"}


@app.post("/coordinator/checkpoint/{run_id}/reject", dependencies=[Depends(require_auth)])
async def reject_checkpoint(run_id: str):
    """Relaie le rejet d'un checkpoint au coordinateur."""
    coordinator_url = os.getenv("COORDINATOR_URL", "http://localhost:3001")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                f"{coordinator_url}/coordinator/checkpoint/{run_id}/reject",
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": f"Erreur coordinateur : {e}"}


_SSE_KEEPALIVE = b": keepalive\n\n"
_SSE_READ_TIMEOUT = 20.0  # secondes sans données → coordinateur considéré muet


@app.get("/events", dependencies=[Depends(require_auth)])
async def events(request: Request):
    """
    Stream SSE — relaie le stream du coordinateur vers le dashboard.
    Envoie un keepalive SSE si le coordinateur est silencieux, et reconnecte
    automatiquement en cas de perte de connexion.
    """
    coordinator_url = os.getenv("COORDINATOR_URL", "http://localhost:3001")

    async def stream():
        while True:
            if await request.is_disconnected():
                return
            try:
                timeout = httpx.Timeout(connect=5.0, read=_SSE_READ_TIMEOUT, write=None, pool=None)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("GET", f"{coordinator_url}/events") as resp:
                        async for chunk in resp.aiter_bytes():
                            if await request.is_disconnected():
                                return
                            yield chunk
            except httpx.ReadTimeout:
                # Coordinateur silencieux — on reste connecté et on envoie un keepalive
                yield _SSE_KEEPALIVE
                await asyncio.sleep(1)
                continue
            except Exception as e:
                yield f"data: {json.dumps({'type': 'notification', 'message': f'Connexion coordinateur perdue : {e}', 'status': 'error'})}\n\n".encode('utf-8')
                await asyncio.sleep(3)

    return StreamingResponse(stream(), media_type="text/event-stream")


# --- Fichiers statiques (build Svelte) ---
# Monté en dernier pour ne pas masquer les routes /api et /events

if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:
    # Fallback pendant le développement (avant le premier npm run build)
    @app.get("/")
    async def read_index():
        return FileResponse(Path(__file__).parent / "templates" / "index.html")
