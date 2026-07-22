*English · [Français](README.fr.md)*

# Cyber Agent Engine

Multi-agent AI system for network automation and security.

An **LLM coordinator** breaks down natural-language requests and delegates execution to **specialized tool agents** (OPNsense, WireGuard, CrowdSec), each driven by a LoRA fine-tuned on a local GPU.

---

## Architecture

```
Utilisateur / UI
      │  langage naturel
      ▼
┌─────────────────────────────────────┐
│         coordinator/  (port 3001)   │
│  PilotAgent : plan → CAP v1 → exec  │
└────────────────┬────────────────────┘
                 │  CAP v1 JSON (Unix socket)
       ┌─────────┼──────────────┐
       ▼         ▼              ▼
   OPNsense   WireGuard     CrowdSec
   (firewall)  (VPN)         (IDPS)
       │
       ▼
   API équipement
```

**CAP v1** (Coordinator-Agent Packet): structured JSON packet passed from the coordinator to the agents. Contains the directive, the entities extracted by AnonyNER, the arguments, and the context.

---

## Structure

```
cyber-agent-engine/
├── server.py                  # Tool-agent-server HTTP (port 3000)
├── coordinator/               # Coordinateur — planification et orchestration
│   ├── pilot.py               # PilotAgent : boucle ReAct
│   ├── judge.py               # CAPValidator : validation déterministe des CAP
│   ├── state.py               # PlanState, Task, CheckpointStore
│   ├── llm/                   # Client LLM multi-backend
│   └── clients/               # Client vers les tool-agent-servers
├── agents/                    # Agents-outils
│   ├── base.py                # ToolAgent : classe de base
│   ├── opnsense/              # Agent OPNsense — 102 fonctions (architecture mixin)
│   ├── wireguard_agent.py     # Agent WireGuard — 11 fonctions
│   ├── crowdsec_agent.py      # Agent CrowdSec — 15 fonctions
│   └── anony/                 # Agent anonymisation (AnonyNER)
├── clients/                   # Clients API bas-niveau
└── dashboard/                 # UI temps réel (Svelte + FastAPI)
```

---

## Stack

- **Local inference**: [vLLM](https://github.com/vllm-project/vllm) with dynamic multi-LoRA loading
- **Fine-tuning**: [Unsloth](https://github.com/unslothai/unsloth) + TRL/PEFT on RTX 4070 Ti
- **Models**: Qwen2.5-3B-Instruct (agents) + Qwen2.5-3B-Instruct (coordinator)
- **Structured output**: Outlines/xgrammar via vLLM `StructuredOutputsParams`
- **Dashboard**: Svelte + TypeScript + Tailwind, real-time SSE
- **Security NER**: custom spaCy (labels: IP, HOSTNAME, CVE, VPN_USER…)

---

## Tool agents

| Agent | Functions | Base model |
|---|---|---|
| OPNsense | 102 (firewall, NAT, IDS, VPN, routing…) | Qwen2.5-3B-Instruct + LoRA |
| WireGuard | 11 (tunnels, peers, keys) | Qwen2.5-3B-Instruct + LoRA |
| CrowdSec | 15 (bans, decisions, alerts) | Qwen2.5-3B-Instruct + LoRA |
| AnonyAgent | 5 (NER anonymization) | spaCy fr_anonyner |

Each agent exposes its capabilities via `GET /capabilities` (OpenAI function-calling format).
The coordinator dynamically discovers the available functions at startup.

---

## Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

```bash
cp .env.example .env
# Fill in the OPNsense, CrowdSec variables and API keys
```

Main variables:

```bash
# OPNsense
OPNSENSE_URL=https://192.168.1.1
OPNSENSE_API_KEY=<clé>
OPNSENSE_API_SECRET=<secret>

# CrowdSec LAPI
CROWDSEC_URL=http://localhost:8080/v1
CROWDSEC_API_KEY=<bouncer-key>

# Modèle de base des agents (LoRA partagé)
TOOL_AGENT_BASE_MODEL=Qwen/Qwen2.5-3B-Instruct
TOOL_AGENT_GPU_UTIL=0.45

# Auth agent-to-agent (omis = mode dev)
AGENT_API_KEY=<clé-forte-aléatoire>
```

## Deployment & backends

### Installation

```bash
pip install cyber-agent-engine          # cœur : coordinateur (API) + agents structurés, sans GPU
pip install cyber-agent-engine[gpu]     # + loader vLLM/LoRA in-process (torch, vllm, unsloth)
```

### Coordinator backend (reasoning LLM)

| Variable                | Role                                                        |
|-------------------------|-------------------------------------------------------------|
| `COORDINATOR_BACKEND`   | `anthropic` (default) \| `openai` \| `vllm` (\[gpu\]) \| `ollama` |
| `ANTHROPIC_API_KEY`     | API key (anthropic backend)                                 |
| `OPENAI_BASE_URL`       | OpenAI-compatible endpoint (OpenRouter, vLLM-HTTP, llama.cpp-server, Ollama `/v1`) |
| `OPENAI_API_KEY`        | key/token of the openai-compatible endpoint                 |

An **OpenAI-compatible** endpoint covers OpenRouter, a vLLM server, llama.cpp
in server mode, LocalAI, and Ollama's `/v1` endpoint — no GPU required on the
`cyber-agent-engine` side.

### LoRA agents (optional NL path)

The trusted path (structured execution via `execute_direct`) requires no
model and always remains available.

To enable LoRA natural-language interpretation:

1. Download the public LoRAs from HuggingFace (opnsense, wireguard, crowdsec).
2. Serve them behind an OpenAI-compatible endpoint (vLLM multi-LoRA, llama.cpp…),
   with the model name = LoRA name.

The agent receives this backend via parameters injected at the `ToolAgent`
constructor level:

- `openai_client`: OpenAI-compatible HTTP client (`OpenAICompatClient`)
- `lora_model`: name of the LoRA to use

**Note:** Automatic wiring from environment variables
(`AGENT_INFER_BASE_URL`, `AGENT_INFER_API_KEY`, `AGENT_LORA_MODELS`) is
planned at the runtime assembly level (sub-project D) and is not yet
active in this package. These variable names remain discoverable for
documentation purposes, but are not read by this module's code.

Without a configured inference backend, the NL path returns an explicit
error (`NoInferenceBackend`); the structured path always remains available.

---

## Getting started

### Tool-agent server

```bash
python server.py
```

Starts the agent server on port 3000. The coordinator reaches it via `AGENT_SERVER_URL`.

### Dashboard

```bash
python dashboard/app.py
```

Starts the real-time interface on port 8080 (checkpoint visualization and approval).

### Running the coordinator

```bash
export COORDINATOR_API_KEY=...            # clé d'auth (obligatoire)
export COORDINATOR_SESSION_KEY=...        # clé Fernet base64 (obligatoire)
export COORDINATOR_POLICY_FILE=policy.yml # règles (obligatoire ; cf. policy.example.yml)
export AGENT_SERVER_URL=http://localhost:3000   # serveur d'agents
cyber-coordinator                          # lance uvicorn sur COORDINATOR_HOST:PORT (défaut 127.0.0.1:8080)
```

The coordinator refuses to start if a mandatory variable is missing or if
`policy.yml` is invalid (fail-closed). Copy `policy.example.yml` as a
starting point. `GET /coordinator/health` serves the readiness probe
(no auth).

---

## API

### `GET /capabilities`

Dynamic discovery of the available functions.

```json
{
  "agents": [
    {
      "name": "opnsense",
      "inference": "vllm",
      "function_count": 102,
      "functions": [
        {
          "name": "block_ip",
          "description": "Bloque une IP via un alias OPNsense.",
          "parameters": { "type": "object", "properties": { "ip": { "type": "string" } } }
        }
      ]
    }
  ]
}
```

### `POST /agent/execute`

Executes a natural-language command.

```bash
curl -X POST http://localhost:3000/agent/execute \
  -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"command": "ban IP 1.2.3.4 pour 24h"}'
```

**Response:**

```json
{
  "success": true,
  "tool_name": "crowdsec",
  "function": "ban_ip",
  "args": {"ip": "1.2.3.4", "duration": "24h"},
  "result": {"status": "banned"}
}
```

Error codes returned to the coordinator:

| Code | Meaning |
|---|---|
| `FUNCTION_UNKNOWN` | No agent recognized the command |
| `MISSING_ARG` | Required argument missing |
| `EXECUTION_ERROR` | Exception during execution |
| `API_UNREACHABLE` | Timeout / connection refused |
| `PERMISSION_DENIED` | HTTP 401/403 from the device |

---

## Architecture decisions

### Mixin architecture (OPNsense)

OPNsense concentrates 102 functions across 13 domains. The code is split into mixins by functional domain (`_filters.py`, `_aliases.py`, `_nat.py`…) and assembled in `_base.py` via multiple inheritance. Python MRO automatically chains the `_register_functions()` calls.

WireGuard (11 functions) and CrowdSec (15 functions) remain single-file — mixins only add value beyond ~15-20 functions across distinct domains.

### Dynamic multi-LoRA

A single vLLM engine loads the base model once and swaps LoRA adapters on the fly depending on the agent called. Discovery of compatible adapters is automatic at startup (filtered by `base_model_name_or_path`).

### Human checkpoint

Before any irreversible action, the coordinator suspends execution and waits for explicit approval via the dashboard or the API. Configurable timeout (`CHECKPOINT_TIMEOUT`, default 300s).

---

## Published models

LoRA adapters fine-tuned on **Qwen2.5-3B-Instruct**, trained with Unsloth on an RTX 4070 Ti, published on HuggingFace.

| Model | Functions | Score | Link |
|---|---|---|---|
| OPNsense agent | 102 (firewall, NAT, IDS, IPsec, ACME, traffic shaping…) | 102/102 — 100% | [patlegu/opnsense-qwen25-lora](https://huggingface.co/patlegu/opnsense-qwen25-lora) |
| WireGuard agent | 11 (tunnels, peers, keys, routing) | 11/11 — 100% | [patlegu/wireguard-qwen25-lora](https://huggingface.co/patlegu/wireguard-qwen25-lora) |
| CrowdSec agent | 15 (bans, decisions, alerts, simulation) | 15/15 — 100% | [patlegu/crowdsec-qwen25-lora](https://huggingface.co/patlegu/crowdsec-qwen25-lora) |

All 3 adapters share the same base — they are loaded simultaneously by vLLM in **dynamic multi-LoRA** mode (swapped on the fly without reloading the backbone).

Functional verification is performed by injecting CAP v1 packets (production format) via the `verify_*_qwen25.py` scripts.

---

## Docker deployment

```bash
cp .env.example .env
# Generate the Fernet session key:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Fill in .env (COORDINATOR_API_KEY, COORDINATOR_SESSION_KEY, AGENT_API_KEY, LLM backend)
# Provide a policy:
cp policy.example.yml policy.yml
docker compose up -d
curl http://localhost:8080/coordinator/health   # {"status":"ok"}
```

The agent server is not exposed on the host; only the coordinator is. The
coordinator refuses to start if a mandatory variable is missing or `policy.yml` is
invalid (fail-closed). GPU image: documented override (CUDA base + `pip install
.[gpu]`), out of scope by default.

## License

This program is free software under **AGPL-3.0-or-later** — see [LICENSE](LICENSE).
Any provision as a network service must be accompanied by publication of the
modified source code.
