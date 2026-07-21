# Cyber Agent Engine

AI multi-agent system for network automation and security.

An **LLM coordinator** breaks down natural language requests and delegates execution to **specialized tool agents** (OPNsense, WireGuard, CrowdSec), each driven by a LoRA fine-tuned on a local GPU.

---

## Architecture

```
User / UI
      │  natural language
      ▼
┌─────────────────────────────────────┐
│         coordinator/  (port 3001)   │
│  PilotAgent: plan → CAP v1 → exec   │
└────────────────┬────────────────────┘
                 │  CAP v1 JSON (Unix socket)
       ┌─────────┼──────────────┐
       ▼         ▼              ▼
   OPNsense   WireGuard     CrowdSec
   (firewall)  (VPN)         (IDPS)
       │
       ▼
   Device API
```

**CAP v1** (Coordinator-Agent Packet): A structured JSON packet transmitted from the coordinator to the agents. It contains the directive, entities extracted by AnonyNER, arguments, and context.

---

## Structure

```
cyber-agent-engine/
├── server.py                  # Tool-agent-server HTTP (port 3000)
├── coordinator/               # Coordinator — planning and orchestration
│   ├── pilot.py               # PilotAgent: ReAct loop
│   ├── judge.py               # CAPValidator: deterministic validation of CAPs
│   ├── state.py               # PlanState, Task, CheckpointStore
│   ├── llm/                   # Multi-backend LLM Client
│   └── clients/               # Client for tool-agent-servers
├── agents/                    # Tool Agents
│   ├── base.py                # ToolAgent: base class
│   ├── opnsense/              # OPNsense Agent — 102 functions (mixin architecture)
│   ├── wireguard_agent.py     # WireGuard Agent — 11 functions
│   ├── crowdsec_agent.py      # CrowdSec Agent — 15 functions
│   └── anony/                 # Anonymization Agent (AnonyNER)
├── clients/                   # Low-level API clients
└── dashboard/                 # Real-time UI (Svelte + FastAPI)
```

---

## Stack

- **Local Inference**: [vLLM](https://github.com/vllm-project/vllm) with dynamic multi-LoRA loading
- **Fine-tuning**: [Unsloth](https://github.com/unslothai/unsloth) + TRL/PEFT on RTX 4070 Ti
- **Models**: Qwen2.5-3B-Instruct (agents) + Qwen2.5-3B-Instruct (coordinator)
- **Structured output**: Outlines/xgrammar via `StructuredOutputsParams` vLLM
- **Dashboard**: Svelte + TypeScript + Tailwind, real-time SSE
- **Security NER**: Custom spaCy (labels: IP, HOSTNAME, CVE, VPN_USER…)

---

## Tool Agents

| Agent | Functions | Base Model |
|---|---|---|
| OPNsense | 102 (firewall, NAT, IDS, VPN, routing…) | Qwen2.5-3B-Instruct + LoRA |
| WireGuard | 11 (tunnels, peers, keys) | Qwen2.5-3B-Instruct + LoRA |
| CrowdSec | 15 (bans, decisions, alerts) | Qwen2.5-3B-Instruct + LoRA |
| AnonyAgent | 5 (NER anonymization) | spaCy fr_anonyner |

Each agent exposes its capabilities via `GET /capabilities` (OpenAI function-calling format).
The coordinator dynamically discovers available functions at startup.

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
# Fill in OPNsense, CrowdSec variables, API keys
```

Main variables:

```bash
# OPNsense
OPNSENSE_URL=https://192.168.1.1
OPNSENSE_API_KEY=<key>
OPNSENSE_API_SECRET=<secret>

# CrowdSec LAPI
CROWDSEC_URL=http://localhost:8080/v1
CROWDSEC_API_KEY=<bouncer-key>

# Base model for agents (shared LoRA)
TOOL_AGENT_BASE_MODEL=Qwen/Qwen2.5-3B-Instruct
TOOL_AGENT_GPU_UTIL=0.45

# Agent-to-agent auth (omitted = dev mode)
AGENT_API_KEY=<strong-random-key>
```

## Startup

```bash
# Tool-agent server (port 3000)
python server.py

# Coordinator (port 3001)
python -m coordinator.server

# Dashboard (port 8080)
python dashboard/app.py
```

---

## API

### `GET /capabilities`

Dynamic discovery of available functions.

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
          "description": "Blocks an IP via an OPNsense alias.",
          "parameters": { "type": "object", "properties": { "ip": { "type": "string" } } }
        }
      ]
    }
  ]
}
```

### `POST /agent/execute`

Executes a command in natural language.

```bash
curl -X POST http://localhost:3000/agent/execute \
  -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"command": "ban IP 1.2.3.4 for 24h"}'
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
| `MISSING_ARG` | Mandatory argument is missing |
| `EXECUTION_ERROR` | Exception during execution |
| `API_UNREACHABLE` | Timeout / connection refused |
| `PERMISSION_DENIED` | HTTP 401/403 from the device |

---

## Architecture Decisions

### Mixin Architecture (OPNsense)

OPNsense has 102 functions across 13 domains. The code is split into mixins by functional domain (`_filters.py`, `_aliases.py`, `_nat.py`…) and assembled in `_base.py` through multiple inheritance. Python's MRO automatically chains the `_register_functions()` calls.

WireGuard (11 functions) and CrowdSec (15 functions) remain in single files — mixins only add value beyond ~15-20 functions across distinct domains.

### Dynamic Multi-LoRA

A single vLLM engine loads the base model once and swaps LoRA adapters on the fly depending on the agent being called. Compatible adapters are discovered automatically at startup (filtered by `base_model_name_or_path`).

### Human Checkpoint

Before any irreversible action, the coordinator suspends execution and waits for explicit approval via the dashboard or API. Configurable timeout (`CHECKPOINT_TIMEOUT`, default 300s).

---

## Published Models

LoRA adapters fine-tuned on **Qwen2.5-3B-Instruct**, trained with Unsloth on an RTX 4070 Ti, published on HuggingFace.

| Model | Functions | Score | Link |
|---|---|---|---|
| OPNsense agent | 102 (firewall, NAT, IDS, IPsec, ACME, traffic shaping…) | 102/102 — 100% | patlegu/opnsense-qwen25-lora |
| WireGuard agent | 11 (tunnels, peers, keys, routing) | 11/11 — 100% | patlegu/wireguard-qwen25-lora |
| CrowdSec agent | 15 (bans, decisions, alerts, simulation) | 15/15 — 100% | patlegu/crowdsec-qwen25-lora |

All 3 adapters share the same base model — they are loaded simultaneously by vLLM using **dynamic multi-LoRA** (swapped on the fly without reloading the backbone).

Functional verification is performed by injecting CAP v1 packets (production format) via the `verify_*_qwen25.py` scripts.