*English · [Français](README.fr.md)*

# Cyber Agent Engine

Multi-agent AI system for network automation and security.

An **LLM coordinator** breaks down natural-language requests and delegates execution to **specialized tool agents** (OPNsense, WireGuard, CrowdSec) through a trust core that enforces fail-closed policy decisions, human approval on irreversible actions, and PII tokenization before anything reaches the LLM. Agents optionally interpret natural language via a LoRA fine-tuned on a local GPU; their structured execution path needs no model at all.

---

## Architecture

```
operator / UI
      │  natural-language request
      ▼
┌───────────────────────────────────────────────────┐
│  coordinator/  (FastAPI, default 127.0.0.1:8080)   │
│                                                     │
│  Proposer (LLM) ──▶ core.decide()  (fail-closed)   │
│                          │                         │
│              ┌───────────┼────────────┐            │
│              ▼           ▼            ▼            │
│            deny       approve       allow          │
│         (stop)      (approval      (execute)       │
│                       gate —                       │
│                       human                        │
│                       checkpoint)                  │
│                          │                         │
│                          ▼                         │
│              core.execution boundary               │
│                                                     │
│  PII tokenization: the LLM only sees tokens         │
└─────────────────────┬───────────────────────────────┘
                       │  HTTP AGENT_SERVER_URL (default :3000)
                       │  UDS optional (AGENT_SERVER_SOCK)
                       ▼
              agent server (server.py)
       ┌───────────┬───────────┬───────────┬─────────┐
       ▼           ▼           ▼           ▼         ▼
   OPNsense    pfSense     WireGuard    CrowdSec    Anony
   (firewall)  (firewall)   (VPN)        (IDPS)    (NER/PII)
       │           │           │           │
       ▼           ▼           ▼           ▼
                devices
```

The trust core (`core/`) sits between the LLM proposer and any real execution:
a fail-closed policy engine decides `deny` / `approve` / `allow` for every
proposed intention, an approval gate suspends the run for irreversible actions
until a human resumes or rejects it, and the execution boundary is the only
code path allowed to call an agent. The LLM never sees raw secrets or PII — it
only ever reads and writes tokens from the vault.

---

## Structure

```
cyber-agent-engine/
├── server.py                  # Agent server HTTP (tool agents), port 3000
├── core/                       # Trust core — the security-relevant path
│   ├── decision.py             # decide(): validate → evaluate → audit → verdict
│   ├── orchestrator.py         # single-action orchestration (shares decide() with the loop)
│   ├── policy/                 # Fail-closed policy engine + capability catalog
│   ├── approval/                # Human approval store
│   ├── audit/                   # Rotating audit sink (size-based)
│   ├── auth/                    # API key auth (X-API-Key)
│   ├── tokens/                  # PII tokenization vault — the LLM only sees tokens
│   └── execution/                # Execution boundary + authorization
├── coordinator/                 # Coordinator — gated ReAct loop
│   ├── app.py                   # FastAPI app: /coordinator/execute, /resume, /reject, /health
│   ├── loop.py                  # GatedLoop: propose → decide → suspend|execute → re-tokenize
│   ├── proposer.py              # LLM proposer — produces an intention, never self-authorizing
│   ├── agent_call.py            # Call into the agent server
│   ├── assembly.py              # Runtime wiring (config → assembled loop)
│   ├── catalog_builder.py       # Builds the capability catalog from agent servers
│   ├── config.py                # Env config, fail-closed on missing secrets
│   ├── extractor.py             # Entity extraction feeding tokenization
│   ├── session.py               # Encrypted session store for suspended runs
│   └── llm/                     # Coordinator LLM backend (anthropic/openai/vllm/ollama)
├── agents/                      # Tool agents (structured execution + optional LoRA NL path)
│   ├── base.py                  # ToolAgent: base class
│   ├── infer_wiring.py          # Wires AGENT_INFER_*/AGENT_LORA_MODELS into each agent
│   ├── opnsense/                # OPNsense agent — 102 functions (mixin architecture)
│   ├── wireguard_agent.py       # WireGuard agent — 11 functions
│   ├── crowdsec_agent.py        # CrowdSec agent — 15 functions
│   ├── pfsense_agent.py         # pfSense agent
│   └── anony/                   # Anonymization agent (AnonyNER)
├── clients/                     # Low-level API clients
├── dashboard/                   # Legacy real-time visualization (Svelte + FastAPI)
└── tests/                       # Test suite
```

---

## Stack

- **Coordinator reasoning**: Anthropic API by default (`COORDINATOR_BACKEND=anthropic`); OpenAI-compatible endpoint or in-process vLLM/Ollama as alternatives
- **Local agent inference (optional)**: [vLLM](https://github.com/vllm-project/vllm) with dynamic multi-LoRA loading
- **Fine-tuning**: [Unsloth](https://github.com/unslothai/unsloth) + TRL/PEFT on RTX 4070 Ti
- **Agent model**: Qwen2.5-3B-Instruct + LoRA (natural-language path; the structured path needs no model)
- **Structured output**: Outlines/xgrammar via vLLM `StructuredOutputsParams`
- **Dashboard (legacy)**: Svelte + TypeScript + Tailwind, real-time SSE
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
pip install -e .            # runtime: coordinator (API) + structured agents, no GPU
pip install -e ".[dev]"     # + dev toolchain (pytest, ruff, mypy, build)
pip install -e ".[gpu]"     # optional: in-process LoRA/vLLM loader (torch, vllm, unsloth)
```

`requirements.txt` at the repository root belongs to the separate LoRA
fine-tuning/training workflow, not to installing this product — do not use it
to install `cyber-agent-engine`.

## Configuration

```bash
cp .env.example .env
# Fill in the coordinator secrets, agent-server key, and LLM backend key
```

`.env.example` covers the **coordinator** side (main variables below); it does
not set OPNsense/CrowdSec device credentials or `TOOL_AGENT_*` — those are
read directly from the process environment by the agent server (`server.py`).

```bash
# Coordinator auth (operator-facing) and session encryption
COORDINATOR_API_KEY=<key>
COORDINATOR_SESSION_KEY=<strong-random-key>   # Fernet base64 key

# Shared agent-server auth (coordinator -> agent server)
AGENT_API_KEY=<strong-random-key>

# Coordinator reasoning LLM backend
COORDINATOR_BACKEND=anthropic
ANTHROPIC_API_KEY=<key>
```

Variables read by the agent server (`server.py`), set separately from `.env.example`:

```bash
# OPNsense
OPNSENSE_URL=https://192.168.1.1
OPNSENSE_API_KEY=<key>
OPNSENSE_API_SECRET=<secret>

# CrowdSec LAPI
CROWDSEC_URL=http://localhost:8080/v1
CROWDSEC_API_KEY=<bouncer-key>

# Base model for agents' optional LoRA natural-language path (code defaults shown)
TOOL_AGENT_BASE_MODEL=microsoft/Phi-3.5-mini-instruct
TOOL_AGENT_GPU_UTIL=0.40
```

## Deployment & backends

### Installation

```bash
pip install cyber-agent-engine          # core: coordinator (API) + structured agents, no GPU
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

**Wiring:** `agents/infer_wiring.py` reads `AGENT_INFER_BASE_URL` /
`AGENT_INFER_API_KEY` / `AGENT_LORA_MODELS` from the environment at agent-server
startup (`server.py`) and injects `openai_client`/`lora_model` into every
`ToolAgent`. A per-agent override, `<AGENT>_LORA_MODEL` (e.g.
`OPNSENSE_LORA_MODEL`), takes precedence over the global `AGENT_LORA_MODELS`
map for that agent.

Without a configured inference backend, the NL path returns an explicit
error (`NoInferenceBackend`); the structured path always remains available.

---

## Getting started

### Tool-agent server

```bash
python server.py
```

Starts the agent server on port 3000. The coordinator reaches it via `AGENT_SERVER_URL`.

### Dashboard (legacy visualization)

```bash
uvicorn dashboard.app:app --port 8090
```

The dashboard is a legacy real-time visualization, kept separate from the
`core`-backed coordinator API below. Its checkpoint-approval routes
(`POST /coordinator/checkpoint/{run_id}/approve` and `/reject`) proxy to a
`COORDINATOR_URL` defaulting to `http://localhost:3001` — the legacy
coordinator API, not the current `coordinator/app.py` (default `:8080`,
see [Coordinator API](#coordinator-api) below). Run it on a port other than
8080/3000/3001 to avoid colliding with the coordinator and agent server.

### Running the coordinator

```bash
export COORDINATOR_API_KEY=...            # authentication key (required)
export COORDINATOR_SESSION_KEY=...        # Fernet base64 key (required)
export COORDINATOR_POLICY_FILE=policy.yml # rules (required; see policy.example.yml)
export AGENT_SERVER_URL=http://localhost:3000   # agent server
cyber-coordinator                          # start uvicorn on COORDINATOR_HOST:PORT (default 127.0.0.1:8080)
```

The coordinator refuses to start if a mandatory variable is missing or if
`policy.yml` is invalid (fail-closed). Copy `policy.example.yml` as a
starting point. `GET /coordinator/health` serves the readiness probe
(no auth).

---

## API

### Coordinator API

Auth via `X-API-Key: <COORDINATOR_API_KEY>`, except `/coordinator/health`.

#### `POST /coordinator/execute`

Runs a natural-language request through the gated loop (propose → decide →
suspend or execute). Body: `{"request": "<text>"}`. Response is one of:
`{"status": "completed", "summary": ..., "results": [...]}`,
`{"status": "pending_approval", "approval_id": "..."}`,
`{"status": "denied", "reason": "..."}`, or
`{"status": "failed", "reason": "..."}`.

```bash
curl -X POST http://localhost:8080/coordinator/execute \
  -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"request": "ban IP 1.2.3.4 for 24h"}'
```

#### `POST /coordinator/resume/{approval_id}`

Resumes a suspended run after a human approves the pending action.

```bash
curl -X POST http://localhost:8080/coordinator/resume/<approval_id> \
  -H "X-API-Key: <key>"
```

#### `POST /coordinator/reject/{approval_id}`

Rejects a pending approval; the run ends `denied`, nothing executes.

```bash
curl -X POST http://localhost:8080/coordinator/reject/<approval_id> \
  -H "X-API-Key: <key>"
```

#### `GET /coordinator/health`

Readiness probe, no auth: `{"status": "ok"}`.

### Agent-server API

#### `GET /capabilities`

Dynamic discovery of the available functions. Requires `X-API-Key`. The
response also carries `server_version` and, per agent, `tool_name` alongside
`name`/`inference`/`function_count`/`functions`.

```json
{
  "server_version": "2.2",
  "agents": [
    {
      "name": "opnsense",
      "tool_name": "opnsense",
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

#### `POST /agent/execute`

Executes a natural-language command.

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

Before any irreversible action, `core.decide` returns `approve`: the coordinator
suspends the run and persists it as a pending approval. A human resumes it with
`POST /coordinator/resume/{approval_id}` (executes) or ends it with
`POST /coordinator/reject/{approval_id}` (denies, nothing runs) — see
[Coordinator API](#coordinator-api). The legacy dashboard offers the same two
actions through its `:3001` proxy. The suspended-session lifetime is a fixed
300s (`session_ttl` in `coordinator/loop.py`), not currently configurable via
an environment variable.

---

## Published models

LoRA adapters fine-tuned on **Qwen2.5-3B-Instruct**, trained with Unsloth on an RTX 4070 Ti, published on HuggingFace.

| Model | Functions | Score | Link |
|---|---|---|---|
| OPNsense agent | 102 (firewall, NAT, IDS, IPsec, ACME, traffic shaping…) | 102/102 — 100% | [patlegu/opnsense-qwen25-lora](https://huggingface.co/patlegu/opnsense-qwen25-lora) |
| WireGuard agent | 11 (tunnels, peers, keys, routing) | 11/11 — 100% | [patlegu/wireguard-qwen25-lora](https://huggingface.co/patlegu/wireguard-qwen25-lora) |
| CrowdSec agent | 15 (bans, decisions, alerts, simulation) | 15/15 — 100% | [patlegu/crowdsec-qwen25-lora](https://huggingface.co/patlegu/crowdsec-qwen25-lora) |

All 3 adapters share the same base — they are loaded simultaneously by vLLM in **dynamic multi-LoRA** mode (swapped on the fly without reloading the backbone).

Functional verification exercises each function exposed by the agent's
`GET /capabilities` catalog end-to-end against the live device API.

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

### Operations

- **Audit retention (bounded disk):** the coordinator's audit log rotates by size.
  Set `COORDINATOR_AUDIT_MAX_BYTES` (default 100 MiB per file) and
  `COORDINATOR_AUDIT_BACKUPS` (default 5); disk use is bounded to roughly
  `max_bytes × (backups + 1)`.
- **Multiple agent servers:** set `AGENT_SERVERS` to a comma-separated list of
  agent-server URLs (e.g. `http://agent-a:3000,http://agent-b:3000`) to route
  different agents to different servers. Empty = the single `AGENT_SERVER_URL`.
  Two servers exposing the same agent name → the coordinator refuses to start
  (ambiguous routing).
- **GPU image:** build `docker build -f Dockerfile.gpu -t cyber-agent-engine:gpu .`
  to serve LoRA agents in-process (installs the `[gpu]` extra: torch, vLLM,
  unsloth). The default image is CPU-only.
- **`policy.example.yml`** ships with the source repository, not the pip wheel —
  copy it from the repo (or write your own from the policy format above).

### Releases & CI

- **CI** (`.github/workflows/ci.yml`): on every push to `main` and every pull
  request, runs ruff (maintained source surface), mypy, and the full test suite.
- **Release** (`.github/workflows/release.yml`): pushing a `v*` tag runs the test
  gate, then publishes the sdist+wheel to **PyPI** (Trusted Publishing / OIDC — no
  stored token) and a CPU Docker image to **GHCR**
  (`ghcr.io/patlegu/cyber-agent-engine:<tag>` + `:latest`).
- **One-time PyPI setup:** create a **Trusted Publisher** on PyPI for project
  `cyber-agent-engine` (owner `patlegu`, repo `cyber-agent-engine`, workflow
  `release.yml`, environment `pypi`). GHCR needs no setup (uses `GITHUB_TOKEN`).
- **Cutting a release:** align `[project].version` in `pyproject.toml`, then
  `git tag vX.Y.Z && git push origin vX.Y.Z` (the tag must equal the version or the
  release job fails).
- The GHCR image is the **CPU** variant; the GPU image is a local build
  (`Dockerfile.gpu`).

## License

This program is free software under **AGPL-3.0-or-later** — see [LICENSE](LICENSE).
Any provision as a network service must be accompanied by publication of the
modified source code.
