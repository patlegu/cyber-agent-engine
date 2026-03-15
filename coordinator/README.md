# Coordinator — Cyber Agent Engine

Serveur de coordination multi-agents. Il reçoit des demandes en langage naturel, les décompose en plan d'exécution via un LLM de raisonnement, et délègue chaque tâche aux agents spécialistes (OPNsense, WireGuard, CrowdSec) via des paquets **CAP v1**.

---

## Architecture

```
Utilisateur / UI
      │  POST /coordinator/execute  {"query": "bloque toutes les IPs chinoises"}
      ▼
┌─────────────────────────────────────────────┐
│            Coordinator (port 3001)          │
│                                             │
│  PilotAgent                                 │
│    1. plan()       — LLM décompose la query │
│    2. execute()    — délègue aux agents     │
│    3. synthesize() — rapport final          │
└──────────────┬──────────────────────────────┘
               │  CAP v1 JSON
       ┌───────┼───────────────┐
       ▼       ▼               ▼
  OPNsense  WireGuard      CrowdSec
  :3000      :3001          :3002
```

### Format CAP v1 (Coordinator-Agent Packet)

```json
{
  "directive": "block_ip",
  "entities": {
    "IP_ADDRESS": ["203.0.113.42"],
    "INTERFACE":  ["wan"],
    "PORT_NUMBER": [], "HOSTNAME": [], "IP_SUBNET": []
  },
  "args":    {"action": "block"},
  "context": {"source": "coordinator", "run_id": "plan-abc-1234", "confidence": 0.97}
}
```

---

## Démarrage

```bash
# Depuis la racine du projet
venv/bin/python -m coordinator.server
# ou
uvicorn coordinator.server:app --host 0.0.0.0 --port 3001
```

---

## Variables d'environnement

| Variable | Défaut | Description |
|---|---|---|
| `COORDINATOR_API_KEY` | *(vide)* | Clé secrète pour le header `X-API-Key`. Si absente → mode dev (accès libre) |
| `COORDINATOR_BACKEND` | `anthropic` | Backend LLM : `anthropic` \| `openai` \| `vllm` \| `ollama` |
| `COORDINATOR_MODEL` | *(voir backend)* | ID du modèle (ex: `claude-sonnet-4-6`, `qwen2.5:7b`) |
| `ANTHROPIC_API_KEY` | — | Clé API Anthropic (backend `anthropic`) |
| `OPENAI_API_KEY` | — | Clé API OpenAI ou token vLLM (backend `openai`) |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | URL de l'API OpenAI-compatible (mettre `http://localhost:8000/v1` pour vLLM) |
| `TOOL_AGENT_URL` | `http://localhost:3000` | URL du tool-agent OPNsense |
| `TOOL_AGENT_KEY` | *(vide)* | Clé API du tool-agent OPNsense |
| `WIREGUARD_AGENT_URL` | `http://localhost:3001` | URL du tool-agent WireGuard |
| `WIREGUARD_AGENT_KEY` | *(vide)* | Clé API du tool-agent WireGuard |
| `CROWDSEC_AGENT_URL` | `http://localhost:3002` | URL du tool-agent CrowdSec |
| `CROWDSEC_AGENT_KEY` | *(vide)* | Clé API du tool-agent CrowdSec |

Exemple `.env` :

```env
COORDINATOR_API_KEY=mon-secret
COORDINATOR_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-...
TOOL_AGENT_URL=http://localhost:3000
TOOL_AGENT_KEY=agent-secret
```

---

## API

Toutes les routes (sauf `/coordinator/health`) requièrent le header :
```
X-API-Key: <COORDINATOR_API_KEY>
```

### `POST /coordinator/execute`

Lance l'exécution d'une demande.

```bash
curl -X POST http://localhost:3001/coordinator/execute \
  -H "X-API-Key: mon-secret" \
  -H "Content-Type: application/json" \
  -d '{"query": "Bloque toutes les connexions depuis la Chine sur le WAN"}'
```

**Réponse — plan exécuté :**
```json
{
  "status": "done",
  "run_id": "plan-abc-1234",
  "objective": "Bloquer le trafic entrant depuis les IPs géolocalisées en Chine",
  "report": "✅ Alias GeoIP créé, règle de blocage WAN appliquée.",
  "tasks": [...]
}
```

**Réponse — approbation requise (HTTP 202) :**
```json
{
  "status": "checkpoint_wait",
  "run_id": "plan-abc-1234",
  "message": "Des actions destructives nécessitent une approbation humaine.",
  "pending_tasks": [...],
  "approve_url": "/coordinator/checkpoint/plan-abc-1234/approve",
  "reject_url":  "/coordinator/checkpoint/plan-abc-1234/reject"
}
```

---

### `GET /coordinator/status/{run_id}`

Retourne l'état complet d'un plan.

```bash
curl http://localhost:3001/coordinator/status/plan-abc-1234 \
  -H "X-API-Key: mon-secret"
```

---

### `GET /coordinator/checkpoint/{run_id}`

Tâches en attente d'approbation (valide uniquement si `status=checkpoint_wait`).

---

### `POST /coordinator/checkpoint/{run_id}/approve`

Approuve les actions destructives et reprend l'exécution en arrière-plan.

```bash
curl -X POST http://localhost:3001/coordinator/checkpoint/plan-abc-1234/approve \
  -H "X-API-Key: mon-secret" \
  -H "Content-Type: application/json" \
  -d '{"comment": "Validé par l'\''opérateur après vérification"}'
```

Poller ensuite `GET /coordinator/status/{run_id}` pour suivre l'avancement.

---

### `POST /coordinator/checkpoint/{run_id}/reject`

Avorte le plan — aucune action destructive n'est exécutée.

---

### `GET /coordinator/capabilities`

Agrège les capacités de tous les tool-agents disponibles.

---

### `GET /coordinator/health`

Liveness check (sans authentification).

```bash
curl http://localhost:3001/coordinator/health
# {"status": "ok", "agents": {"opnsense": "http://localhost:3000", ...}}
```

---

## Backends LLM

| Backend | Config | Modèle recommandé |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` (défaut) |
| `openai` | `OPENAI_API_KEY` + `OPENAI_BASE_URL` | GPT-4o ou vLLM |
| `vllm` | Instance vLLM locale | `Qwen/Qwen2.5-7B-Instruct` |
| `ollama` | Ollama démarré localement | `qwen2.5:7b` |

Le backend `anthropic` est recommandé en production — le coordinateur est le cerveau du système, il bénéficie d'un modèle capable de raisonnement complexe et de planification multi-étapes.

---

## Structure interne

```
coordinator/
├── server.py          — API FastAPI (routes, auth, lifespan)
├── pilot.py           — PilotAgent : plan → execute → synthesize
├── models.py          — CoordinatorDirective (CAP v1), schémas Pydantic
├── state.py           — PlanState, Task, CheckpointStore (in-memory)
├── llm/
│   └── coordinator_llm.py  — Client LLM multi-backend
├── clients/
│   └── tool_agent_client.py — Client HTTP vers les tool-agent-servers
└── prompts/
    ├── system.yaml     — System prompt du coordinateur
    ├── planning.yaml   — Prompt de décomposition en tâches (few-shot)
    ├── routing.yaml    — Prompt de reformulation après MISSING_ARG
    └── synthesis.yaml  — Prompt de génération du rapport final
```

---

## Limites connues

- `CheckpointStore` en mémoire uniquement — les états sont perdus au redémarrage
- Un seul niveau d'approbation (approve/reject global, pas tâche par tâche)
