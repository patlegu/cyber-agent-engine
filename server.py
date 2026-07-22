
import os
import sys
import json
import logging
import asyncio
import psutil
import httpx
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv

from fastapi import FastAPI, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.auth.api_key import load_auth_secret, make_auth_dependency

# Add project root to path
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from agents.opnsense_agent import OPNsenseAgent
from agents.wireguard_agent import WireGuardAgent
from agents.crowdsec_agent import CrowdSecAgent
from agents.base import ToolResult
from agents.classifier import AgentClassifier
from agents.contracts import AgentExecuteRequest, AgentExecuteResponse

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("agent_server")

# Global State
agents: Dict[str, Any] = {}
vllm_client = None
_http_client: Optional[httpx.AsyncClient] = None
_opnsense_http_client: Optional[httpx.AsyncClient] = None
_classifier = AgentClassifier()

# Configuration
load_dotenv()
OPNSENSE_URL    = os.getenv("OPNSENSE_URL", "https://192.168.1.1")
OPNSENSE_KEY    = os.getenv("OPNSENSE_API_KEY")
OPNSENSE_SECRET = os.getenv("OPNSENSE_API_SECRET")
CROWDSEC_URL    = os.getenv("CROWDSEC_URL", "http://localhost:8080/v1")
CROWDSEC_KEY    = os.getenv("CROWDSEC_API_KEY")
VLLM_PORT       = 8000
CORS_ORIGINS    = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]

# Auth — header X-API-Key, fail-closed : sans AGENT_API_KEY configurée, le
# serveur refuse de démarrer (AuthNotConfigured levée par load_auth_secret).
_AGENT_SECRET = load_auth_secret(os.environ, "AGENT_API_KEY")
verify_api_key = make_auth_dependency(_AGENT_SECRET)

# Data Models — les contrats API inter-services sont dans agents/contracts.py
# CommandRequest conservé comme alias pour la rétrocompatibilité des clients existants
class CommandRequest(BaseModel):
    command: str

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

def _discover_lora_adapters(loras_dir: Path, base_model: str) -> Dict[str, str]:
    """
    Scanne loras_dir et retourne un dict {agent_name: adapter_path} pour les
    adapters dont base_model_name_or_path correspond au modèle chargé.

    Convention de nommage des répertoires :
      <agent>_lora/            → ex: opnsense_lora/       → agent_name "opnsense"
      <agent>_<variant>_lora/  → ex: opnsense_qwen25_lora/ → agent_name "opnsense"

    Les suffixes de variante modèle (_qwen25, _qwen3, _phi3, _phi35) sont retirés
    pour normaliser au tool_name réel de l'agent (ex: "opnsense_qwen25" → "opnsense").
    Cela permet à _infer_with_vllm() d'utiliser adapter_name=self.tool_name sans
    connaitre la variante de modèle courante.

    Les adapters incompatibles (base model différent) sont loggués en WARNING.
    """
    import json as _json

    # Suffixes de variante à retirer après _lora strip
    _MODEL_VARIANTS = ("_qwen25", "_qwen3", "_phi3", "_phi35")

    adapters: Dict[str, str] = {}
    if not loras_dir.is_dir():
        return adapters

    for lora_dir in sorted(loras_dir.iterdir()):
        adapter_path = lora_dir / "adapter"
        config_path  = adapter_path / "adapter_config.json"
        if not config_path.exists():
            continue

        try:
            cfg = _json.loads(config_path.read_text())
        except Exception as e:
            logger.warning("Impossible de lire %s : %s", config_path, e)
            continue

        adapter_base = cfg.get("base_model_name_or_path", "")

        # Normaliser le nom : retirer _lora puis les suffixes de variante modèle
        raw_name   = lora_dir.name.removesuffix("_lora")
        agent_name = raw_name
        for variant in _MODEL_VARIANTS:
            if agent_name.endswith(variant):
                agent_name = agent_name[: -len(variant)]
                break

        if adapter_base == base_model:
            adapters[agent_name] = str(adapter_path)
            logger.info("  ✅ Adapter '%s' compatible (%s)", agent_name, adapter_base)
        else:
            logger.warning(
                "  ⚠️  Adapter '%s' ignoré — base model incompatible "
                "(adapter: %s, attendu: %s). Re-entraîner sur %s pour activer.",
                agent_name, adapter_base, base_model, base_model,
            )

    return adapters


# Lifecycle Manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Starting Cyber Agent Server...")
    global vllm_client, _http_client, _opnsense_http_client

    # Persistent HTTP clients for health checks
    _http_client = httpx.AsyncClient(timeout=httpx.Timeout(0.5))
    _opnsense_http_client = httpx.AsyncClient(verify=False, timeout=httpx.Timeout(1.0))
    
    # 1. Initialize vLLM
    # Chargement dynamique des adapters compatibles avec le modèle de base configuré.
    # Un adapter est compatible si son adapter_config.json déclare la même base model.
    # Les adapters incompatibles (base model différent) sont ignorés avec un warning —
    # l'agent correspondant fonctionnera en fallback Ollama/simulation.
    base_model = os.getenv("TOOL_AGENT_BASE_MODEL", "microsoft/Phi-3.5-mini-instruct")
    try:
        lora_adapters = _discover_lora_adapters(ROOT_DIR / "loras", base_model)
        if lora_adapters:
            logger.info(f"🧠 Initializing vLLM Engine (base: {base_model}) with adapters: {list(lora_adapters.keys())}")
            from clients.gpu import load_native_vllm_client
            NativeVLLMClient = load_native_vllm_client()  # lève GpuExtraRequired si [gpu] absent
            vllm_client = NativeVLLMClient(
                model_path=base_model,
                lora_adapters=lora_adapters,
                gpu_utilization=float(os.getenv("TOOL_AGENT_GPU_UTIL", "0.40")),
                max_model_len=int(os.getenv("TOOL_AGENT_MAX_MODEL_LEN", "4096"))
            )
        else:
            logger.warning("⚠️ No compatible LoRA adapters found. Agents will run in fallback mode.")

    except Exception as e:
        logger.error(f"❌ Failed to initialize vLLM: {e}")

    # 2. Initialize Agents
    api_config = {
        "base_url": OPNSENSE_URL,
        "api_key": OPNSENSE_KEY,
        "api_secret": OPNSENSE_SECRET,
        "verify_ssl": os.getenv("OPNSENSE_VERIFY_SSL", "False").lower() == "true",
        "timeout": int(os.getenv("OPNSENSE_TIMEOUT", 30))
    }
    
    ollama_config = {
        "url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "model": os.getenv("OLLAMA_MODEL", "opnsense-phi3")
    }

    # Backend d'inférence OpenAI-compatible partagé (fail-closed : None si
    # AGENT_INFER_BASE_URL absent, les agents retombent alors sur ollama/vllm).
    from agents.infer_wiring import build_infer_client, resolve_lora_models
    _infer_client = build_infer_client(os.environ)
    _lora_models = resolve_lora_models(os.environ)

    # OPNsense Agent
    agents["opnsense"] = OPNsenseAgent(
        model_path=None,
        api_config=api_config if OPNSENSE_KEY else None,
        ollama_config=ollama_config,
        vllm_client=vllm_client,
        openai_client=_infer_client,
        lora_model=_lora_models.get("opnsense", ""),
    )

    # WireGuard Agent
    agents["wireguard"] = WireGuardAgent(
        platform="opnsense",
        config=api_config if OPNSENSE_KEY else None,
        ollama_config=ollama_config,
        model_path=None,
        simulation_mode=(OPNSENSE_KEY is None),
        vllm_client=vllm_client,
        openai_client=_infer_client,
        lora_model=_lora_models.get("wireguard", ""),
    )

    # CrowdSec Agent
    crowdsec_config = {
        "base_url": CROWDSEC_URL,
        "api_key": CROWDSEC_KEY,
        "verify_ssl": False,
    } if CROWDSEC_KEY else None
    agents["crowdsec"] = CrowdSecAgent(
        model_path=None,
        api_config=crowdsec_config,
        ollama_config=ollama_config,
        vllm_client=vllm_client,
        openai_client=_infer_client,
        lora_model=_lora_models.get("crowdsec", ""),
    )

    logger.info("✅ Agents initialized.")

    yield

    # Shutdown
    logger.info("🛑 Shutting down server...")
    if vllm_client:
        vllm_client.shutdown()
    if _infer_client is not None:
        await _infer_client.aclose()
    if _http_client:
        await _http_client.aclose()
    if _opnsense_http_client:
        await _opnsense_http_client.aclose()

app = FastAPI(title="Cyber Agent Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# --- Routes ---

@app.get("/")
async def read_index():
    return FileResponse("dashboard/templates/index.html")

@app.post("/agent/execute", dependencies=[Depends(verify_api_key)])
async def execute_command(request: AgentExecuteRequest) -> AgentExecuteResponse:
    """
    Exécute une commande sur les agents persistants.

    Deux modes :
    - **Naturel** (`command`) : le vLLM classifie l'intention et choisit la fonction
    - **Structuré** (`function` + `args`) : exécution directe, sans inférence LLM
    """

    def _response(result: ToolResult) -> AgentExecuteResponse:
        return AgentExecuteResponse(
            success=result.success,
            tool_name=result.tool_name,
            function=result.function,
            args=result.args or {},
            result=result.result,
            error=result.error,
            error_code=result.error_code,
            reasoning=result.reasoning,
            execution_time_ms=result.execution_time_ms,
        )

    # --- Mode structuré : bypass LLM ---
    if request.function:
        logger.info(f"📥 Direct call: {request.function}({request.args})")
        target_agent_name, _, _entities = _classifier.classify(request.function)
        agent = agents.get(target_agent_name) or next(iter(agents.values()), None)
        if agent is None:
            resp = AgentExecuteResponse(
                success=False, error="No agent available", error_code="FUNCTION_UNKNOWN"
            )
            return JSONResponse(status_code=400, content=resp.model_dump())
        result = await agent.execute_direct(request.function, request.args)
        if result.reasoning:
            logger.info(f"🧠 Reasoning: {result.reasoning}")
        resp = _response(result)
        if not result.success:
            return JSONResponse(status_code=400, content=resp.model_dump())
        return resp

    # --- Mode naturel : classification + inférence LLM ---
    command = request.command
    logger.info(f"📥 Received command: {command}")
    target_agent_name, confidence, _entities = _classifier.classify(command)
    logger.info(f"Intent classified as '{target_agent_name}' (confidence={confidence:.2f})")

    available = list(agents.keys())
    priority_list = [agents[target_agent_name]] + [agents[a] for a in available if a != target_agent_name]

    for agent in priority_list:
        try:
            result = await agent.execute(command)

            if result.function != "unknown":
                if result.reasoning:
                    logger.info(f"🧠 Reasoning: {result.reasoning}")
                resp = _response(result)
                if not result.success:
                    # Agent identified the intent but execution failed.
                    # Return directly — do not fall back to other agents.
                    return JSONResponse(status_code=400, content=resp.model_dump())
                return resp
        except Exception as e:
            logger.error(f"Agent execution error: {e}")

    resp = AgentExecuteResponse(
        success=False,
        error="Aucun agent n'a pu interpréter cette commande.",
        error_code="FUNCTION_UNKNOWN",
        tool_name="server",
    )
    return JSONResponse(status_code=400, content=resp.model_dump())

@app.get("/capabilities", dependencies=[Depends(verify_api_key)])
async def get_capabilities():
    """
    Return the list of all functions exposed by each agent.
    Used by coordinator agents for dynamic tool discovery.
    Response follows OpenAI function-calling schema conventions.
    """
    agent_caps = []
    for name, agent in agents.items():
        caps = agent.get_capabilities()
        inference_mode = "simulation"
        if getattr(agent, "vllm_client", None):
            inference_mode = "vllm"
        elif getattr(agent, "ollama_client", None):
            inference_mode = "ollama"
        agent_caps.append({
            "name": name,
            "tool_name": agent.tool_name,
            "inference": inference_mode,
            "function_count": len(caps),
            "functions": caps,
        })

    return {
        "server_version": "2.2",
        "agents": agent_caps,
    }


@app.get("/api/status", response_model=DashboardStatus)
async def get_status():
    # 1. System Stats
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    
    # 2. Network Stats
    internet = False
    try:
        resp = await _http_client.get("https://1.1.1.1")
        if resp.status_code == 200:
            internet = True
    except Exception:
        pass

    opnsense = False
    opnsense_det = "Unreachable"
    if OPNSENSE_KEY:
        try:
            resp = await _opnsense_http_client.get(
                f"{OPNSENSE_URL}/api/core/system/status",
                auth=(OPNSENSE_KEY, OPNSENSE_SECRET)
            )
            if resp.status_code == 200:
                opnsense = True
                opnsense_det = "Online"
            else:
                opnsense_det = f"HTTP {resp.status_code}"
        except Exception:
            opnsense_det = "Connection Failed"
    else:
        opnsense = True
        opnsense_det = "Simulation"

    # 3. Agent Stats
    vllm_ok = (vllm_client is not None)
    
    return {
        "system": {"cpu_percent": cpu, "memory_percent": mem, "disk_percent": disk},
        "network": {"internet": internet, "opnsense": opnsense, "opnsense_details": opnsense_det},
        "agent": {"vllm_status": vllm_ok, "model_loaded": vllm_ok}
    }

if __name__ == "__main__":
    import signal
    import uvicorn
    import pathlib

    uds_path = os.getenv("UDS_SOCKET_PATH", "")
    if uds_path:
        pathlib.Path(uds_path).parent.mkdir(parents=True, exist_ok=True)
        print(f"Tool-agent server starting on UDS: {uds_path}")
        config = uvicorn.Config("server:app", uds=uds_path, reload=False,
                                timeout_graceful_shutdown=30)
    else:
        port = int(os.getenv("TOOL_AGENT_PORT", "3000"))
        print(f"Tool-agent server starting on http://0.0.0.0:{port}")
        config = uvicorn.Config("server:app", host="0.0.0.0", port=port, reload=False,
                                timeout_graceful_shutdown=30)

    server = uvicorn.Server(config)

    # Intercept SIGINT/SIGTERM before uvicorn installs its own handlers.
    # Setting server.should_exit triggers uvicorn's graceful shutdown path
    # (lifespan __aexit__ → vllm_client.shutdown() → del llm → EngineCore stops via IPC).
    # This prevents the EngineCore subprocess from receiving raw SIGINT and
    # dying with the "destroy_process_group() was not called" NCCL warning.
    server.install_signal_handlers = lambda: None

    def _handle_exit(signum, frame):
        logger.info("Signal %d received — graceful shutdown… (press again to force quit)", signum)
        server.should_exit = True
        # Restore default handlers: a second CTRL+C will kill immediately.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)

    server.run()
