# Cyber Agent Engine

Système multi-agents IA pour l'automatisation réseau et la sécurité.

Un **coordinateur LLM** décompose les demandes en langage naturel et délègue l'exécution à des **agents-outils spécialisés** (OPNsense, WireGuard, CrowdSec), chacun piloté par un LoRA fine-tuné sur GPU local.

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

**CAP v1** (Coordinator-Agent Packet) : paquet JSON structuré transmis du coordinateur aux agents. Contient la directive, les entités extraites par AnonyNER, les arguments et le contexte.

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

- **Inférence locale** : [vLLM](https://github.com/vllm-project/vllm) avec chargement multi-LoRA dynamique
- **Fine-tuning** : [Unsloth](https://github.com/unslothai/unsloth) + TRL/PEFT sur RTX 4070 Ti
- **Modèles** : Qwen2.5-3B-Instruct (agents) + Qwen2.5-3B-Instruct (coordinateur)
- **Structured output** : Outlines/xgrammar via `StructuredOutputsParams` vLLM
- **Dashboard** : Svelte + TypeScript + Tailwind, SSE temps réel
- **NER sécurité** : spaCy custom (labels : IP, HOSTNAME, CVE, VPN_USER…)

---

## Agents-outils

| Agent | Fonctions | Modèle de base |
|---|---|---|
| OPNsense | 102 (firewall, NAT, IDS, VPN, routing…) | Qwen2.5-3B-Instruct + LoRA |
| WireGuard | 11 (tunnels, peers, clés) | Qwen2.5-3B-Instruct + LoRA |
| CrowdSec | 15 (bans, décisions, alertes) | Qwen2.5-3B-Instruct + LoRA |
| AnonyAgent | 5 (anonymisation NER) | spaCy fr_anonyner |

Chaque agent expose ses capacités via `GET /capabilities` (format OpenAI function-calling).
Le coordinateur découvre dynamiquement les fonctions disponibles au démarrage.

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
# Renseigner les variables OPNsense, CrowdSec, clés API
```

Variables principales :

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

## Démarrage

```bash
# Tool-agent server (port 3000)
python server.py

# Coordinateur (port 3001)
python -m coordinator.server

# Dashboard (port 8080)
python dashboard/app.py
```

---

## API

### `GET /capabilities`

Découverte dynamique des fonctions disponibles.

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

Exécute une commande en langage naturel.

```bash
curl -X POST http://localhost:3000/agent/execute \
  -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"command": "ban IP 1.2.3.4 pour 24h"}'
```

**Réponse :**

```json
{
  "success": true,
  "tool_name": "crowdsec",
  "function": "ban_ip",
  "args": {"ip": "1.2.3.4", "duration": "24h"},
  "result": {"status": "banned"}
}
```

Codes d'erreur retournés au coordinateur :

| Code | Signification |
|---|---|
| `FUNCTION_UNKNOWN` | Aucun agent n'a reconnu la commande |
| `MISSING_ARG` | Argument obligatoire absent |
| `EXECUTION_ERROR` | Exception lors de l'exécution |
| `API_UNREACHABLE` | Timeout / connexion refusée |
| `PERMISSION_DENIED` | HTTP 401/403 de l'équipement |

---

## Décisions d'architecture

### Architecture mixin (OPNsense)

OPNsense concentre 102 fonctions sur 13 domaines. Le code est découpé en mixins par domaine fonctionnel (`_filters.py`, `_aliases.py`, `_nat.py`…) et assemblé dans `_base.py` par héritage multiple. Python MRO chaîne automatiquement les `_register_functions()`.

WireGuard (11 fonctions) et CrowdSec (15 fonctions) restent en fichier unique — les mixins n'apportent de la valeur qu'au-delà de ~15-20 fonctions sur des domaines distincts.

### Multi-LoRA dynamique

Un seul moteur vLLM charge le modèle de base une fois et swap les adapters LoRA à la volée selon l'agent appelé. La découverte des adapters compatibles est automatique au démarrage (filtrage par `base_model_name_or_path`).

### Checkpoint humain

Avant toute action irréversible, le coordinateur suspend l'exécution et attend une approbation explicite via le dashboard ou l'API. Timeout configurable (`CHECKPOINT_TIMEOUT`, défaut 300s).

---

## Modèles publiés

Adapters LoRA fine-tunés sur **Qwen2.5-3B-Instruct**, entraînés avec Unsloth sur RTX 4070 Ti, publiés sur HuggingFace.

| Modèle | Fonctions | Score | Lien |
|---|---|---|---|
| OPNsense agent | 102 (firewall, NAT, IDS, IPsec, ACME, traffic shaping…) | 102/102 — 100% | [patlegu/opnsense-qwen25-lora](https://huggingface.co/patlegu/opnsense-qwen25-lora) |
| WireGuard agent | 11 (tunnels, peers, clés, routage) | 11/11 — 100% | [patlegu/wireguard-qwen25-lora](https://huggingface.co/patlegu/wireguard-qwen25-lora) |
| CrowdSec agent | 15 (bans, décisions, alertes, simulation) | 15/15 — 100% | [patlegu/crowdsec-qwen25-lora](https://huggingface.co/patlegu/crowdsec-qwen25-lora) |

Les 3 adapters partagent la même base — ils sont chargés simultanément par vLLM en **multi-LoRA dynamique** (swap à la volée sans recharger le backbone).

La vérification fonctionnelle est réalisée par injection de paquets CAP v1 (format production) via les scripts `verify_*_qwen25.py`.
