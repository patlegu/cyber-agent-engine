*[English](README.md) · Français*

# Cyber Agent Engine

Système multi-agents IA pour l'automatisation réseau et la sécurité.

Un **coordinateur LLM** décompose les demandes en langage naturel et délègue l'exécution à des **agents-outils spécialisés** (OPNsense, WireGuard, CrowdSec) via un socle de confiance (trust core) qui impose des décisions de politique fail-closed, une approbation humaine sur les actions irréversibles, et une tokenisation des PII avant que quoi que ce soit n'atteigne le LLM. Les agents interprètent optionnellement le langage naturel via un LoRA fine-tuné sur GPU local ; leur chemin d'exécution structuré ne requiert aucun modèle.

---

## Architecture

```
opérateur / UI
      │  requête en langage naturel
      ▼
┌───────────────────────────────────────────────────┐
│  coordinator/  (FastAPI, défaut 127.0.0.1:8080)    │
│                                                     │
│  Proposer (LLM) ──▶ core.decide()  (fail-closed)   │
│                          │                         │
│              ┌───────────┼────────────┐            │
│              ▼           ▼            ▼            │
│            deny       approve       allow          │
│         (arrêt)      (porte             (exécute)  │
│                       d'approbation —              │
│                       checkpoint                   │
│                       humain)                      │
│                          │                         │
│                          ▼                         │
│              frontière core.execution              │
│                                                     │
│  Tokenisation PII : le LLM ne voit que des jetons   │
└─────────────────────┬───────────────────────────────┘
                       │  HTTP AGENT_SERVER_URL (défaut :3000)
                       │  UDS optionnel (AGENT_SERVER_SOCK)
                       ▼
              serveur d'agents (server.py)
       ┌────────────────────────────────────────────┐
       │ enregistrés : opnsense, wireguard, crowdsec│
       ├───────────┬───────────┬───────────┐        │
       │ ▼         ▼           ▼           ▼        │
       │ OPNsense  WireGuard   CrowdSec            │
       │ (firewall) (VPN)      (IDPS)              │
       └───────────┴───────────┴───────────┘        │
                                                     │
       pfSense (disponible en code, non enregistré)  │
       Anony (in-process côté coordinateur)         │
       │           │           │
       ▼           ▼           ▼
                équipements
```

Le socle de confiance (`core/`) se situe entre le proposer LLM et toute
exécution réelle : un moteur de politique fail-closed décide `deny` /
`approve` / `allow` pour chaque intention proposée, une porte d'approbation
suspend l'exécution pour les actions irréversibles jusqu'à ce qu'un humain la
reprenne ou la rejette, et la frontière d'exécution est le seul chemin de code
autorisé à appeler un agent. Le LLM ne voit jamais les secrets ou les PII en
clair — il ne lit et n'écrit que des jetons du vault.

---

## Structure

```
cyber-agent-engine/
├── server.py                  # Serveur d'agents HTTP (agents-outils), port 3000
├── core/                       # Socle de confiance — le chemin sensible pour la sécurité
│   ├── decision.py             # decide() : valider → évaluer → auditer → verdict
│   ├── orchestrator.py         # Orchestration mono-action (partage decide() avec la boucle)
│   ├── policy/                 # Moteur de politique fail-closed + catalogue de capacités
│   ├── approval/                # Registre des approbations humaines
│   ├── audit/                   # Log d'audit rotatif (par taille)
│   ├── auth/                    # Auth par clé API (X-API-Key)
│   ├── tokens/                  # Vault de tokenisation PII — le LLM ne voit que des jetons
│   └── execution/                # Frontière d'exécution + autorisation
├── coordinator/                 # Coordinateur — boucle ReAct gatée
│   ├── app.py                   # App FastAPI : /coordinator/execute, /resume, /reject, /health
│   ├── loop.py                  # GatedLoop : proposer → décider → suspendre|exécuter → re-tokeniser
│   ├── proposer.py              # Proposer LLM — produit une intention, jamais auto-autorisante
│   ├── agent_call.py            # Appel vers le serveur d'agents
│   ├── assembly.py              # Câblage runtime (config → boucle assemblée)
│   ├── catalog_builder.py       # Construit le catalogue de capacités depuis les serveurs d'agents
│   ├── config.py                # Config env, fail-closed si secrets manquants
│   ├── extractor.py             # Extraction d'entités alimentant la tokenisation
│   ├── session.py                # Registre de sessions chiffré pour les exécutions suspendues
│   └── llm/                      # Backend LLM du coordinateur (anthropic/openai/vllm/ollama)
├── agents/                       # Agents-outils (exécution structurée + chemin NL LoRA optionnel)
│   ├── base.py                   # ToolAgent : classe de base
│   ├── infer_wiring.py           # Câble AGENT_INFER_*/AGENT_LORA_MODELS dans chaque agent
│   ├── opnsense/                 # Agent OPNsense — 102 fonctions (architecture mixin)
│   ├── wireguard_agent.py        # Agent WireGuard — 11 fonctions
│   ├── crowdsec_agent.py         # Agent CrowdSec — 15 fonctions
│   ├── pfsense_agent.py          # Agent pfSense
│   └── anony/                    # Agent anonymisation (AnonyNER)
├── clients/                      # Clients API bas-niveau
├── dashboard/                    # Visualisation temps réel legacy (Svelte + FastAPI)
└── tests/                        # Suite de tests
```

---

## Stack

- **Raisonnement du coordinateur** : API Anthropic par défaut (`COORDINATOR_BACKEND=anthropic`) ; endpoint OpenAI-compatible ou vLLM/Ollama in-process en alternative
- **Inférence locale des agents (optionnelle)** : [vLLM](https://github.com/vllm-project/vllm) avec chargement multi-LoRA dynamique
- **Fine-tuning** : [Unsloth](https://github.com/unslothai/unsloth) + TRL/PEFT sur RTX 4070 Ti
- **Modèle des agents** : Qwen2.5-3B-Instruct + LoRA (chemin langage naturel ; le chemin structuré ne requiert aucun modèle)
- **Structured output** : Outlines/xgrammar via `StructuredOutputsParams` vLLM
- **Dashboard (legacy)** : Svelte + TypeScript + Tailwind, SSE temps réel
- **NER sécurité** : spaCy custom (labels : IP, HOSTNAME, CVE, VPN_USER…)

---

## Agents-outils

| Agent | Fonctions | Modèle de base |
|---|---|---|
| OPNsense | 102 (firewall, NAT, IDS, VPN, routing…) | Qwen2.5-3B-Instruct + LoRA |
| WireGuard | 11 (tunnels, peers, clés) | Qwen2.5-3B-Instruct + LoRA |
| CrowdSec | 15 (bans, décisions, alertes) | Qwen2.5-3B-Instruct + LoRA |
| AnonyAgent | 5 (anonymisation NER) | spaCy fr_anonyner |

Les trois **agents enregistrés** (OPNsense, WireGuard, CrowdSec) exposent leurs
capacités via `GET /capabilities` (format OpenAI function-calling) servi par le
serveur d'agents. Le coordinateur découvre dynamiquement les fonctions
disponibles au démarrage. AnonyAgent exécute in-process côté coordinateur, non
servi par le serveur d'agents.

---

## Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -e .            # runtime : coordinateur (API) + agents structurés, sans GPU
pip install -e ".[dev]"     # + chaîne d'outils dev (pytest, ruff, mypy, build)
pip install -e ".[gpu]"     # optionnel : loader LoRA/vLLM in-process (torch, vllm, unsloth)
```

`requirements.txt` à la racine du dépôt appartient au workflow séparé de
fine-tuning/entraînement des LoRA, pas à l'installation de ce produit — ne pas
l'utiliser pour installer `cyber-agent-engine`.

## Configuration

```bash
cp .env.example .env
# Renseigner les secrets du coordinateur, la clé du serveur d'agents et la clé du backend LLM
```

`.env.example` couvre le côté **coordinateur** (variables principales
ci-dessous) ; il ne définit ni les identifiants d'équipement OPNsense/CrowdSec
ni `TOOL_AGENT_*` — ceux-ci sont lus directement dans l'environnement du
processus par le serveur d'agents (`server.py`).

```bash
# Auth du coordinateur (côté opérateur) et chiffrement de session
COORDINATOR_API_KEY=<clé>
COORDINATOR_SESSION_KEY=<clé-forte-aléatoire>   # clé Fernet base64

# Auth partagée serveur d'agents (coordinateur -> serveur d'agents)
AGENT_API_KEY=<clé-forte-aléatoire>

# Backend LLM de raisonnement du coordinateur
COORDINATOR_BACKEND=anthropic
ANTHROPIC_API_KEY=<clé>
```

Variables lues par le serveur d'agents (`server.py`), à définir séparément de `.env.example` :

```bash
# OPNsense
OPNSENSE_URL=https://192.168.1.1
OPNSENSE_API_KEY=<clé>
OPNSENSE_API_SECRET=<secret>

# CrowdSec LAPI
CROWDSEC_URL=http://localhost:8080/v1
CROWDSEC_API_KEY=<bouncer-key>

# Modèle de base des agents pour le chemin NL LoRA optionnel (défauts code affichés)
TOOL_AGENT_BASE_MODEL=microsoft/Phi-3.5-mini-instruct
TOOL_AGENT_GPU_UTIL=0.40
```

## Déploiement & backends

### Installation

```bash
pip install cyber-agent-engine          # cœur : coordinateur (API) + agents structurés, sans GPU
pip install cyber-agent-engine[gpu]     # + loader vLLM/LoRA in-process (torch, vllm, unsloth)
```

### Backend du coordinateur (LLM de raisonnement)

| Variable                | Rôle                                                        |
|-------------------------|-------------------------------------------------------------|
| `COORDINATOR_BACKEND`   | `anthropic` (défaut) \| `openai` \| `vllm` (\[gpu\]) \| `ollama` |
| `ANTHROPIC_API_KEY`     | clé API (backend anthropic)                                 |
| `OPENAI_BASE_URL`       | endpoint OpenAI-compatible (OpenRouter, vLLM-HTTP, llama.cpp-server, Ollama `/v1`) |
| `OPENAI_API_KEY`        | clé/token du endpoint openai-compatible                     |

Un endpoint **OpenAI-compatible** couvre OpenRouter, un serveur vLLM, llama.cpp
en mode serveur, LocalAI, et l'endpoint `/v1` d'Ollama — aucun GPU requis côté
`cyber-agent-engine`.

### Agents LoRA (chemin NL optionnel)

Le chemin de confiance (exécution structurée via `execute_direct`) ne requiert
aucun modèle et reste toujours disponible.

Pour activer l'interprétation en langage naturel par LoRA :

1. Télécharger les LoRA publics depuis HuggingFace (opnsense, wireguard, crowdsec).
2. Les servir derrière un endpoint OpenAI-compatible (vLLM multi-LoRA, llama.cpp…),
   le nom de modèle = nom du LoRA.

L'agent reçoit ce backend via les paramètres injectés au niveau du constructeur
`ToolAgent` :

- `openai_client` : client HTTP OpenAI-compatible (`OpenAICompatClient`)
- `lora_model` : nom du LoRA à utiliser

**Câblage :** `agents/infer_wiring.py` lit `AGENT_INFER_BASE_URL` /
`AGENT_INFER_API_KEY` / `AGENT_LORA_MODELS` dans l'environnement au démarrage
du serveur d'agents (`server.py`) et injecte `openai_client`/`lora_model` dans
chaque `ToolAgent`. Une surcharge par agent, `<AGENT>_LORA_MODEL` (ex.
`OPNSENSE_LORA_MODEL`), prime sur la map globale `AGENT_LORA_MODELS` pour cet
agent.

Sans backend d'inférence configuré, le chemin NL renvoie une erreur explicite
(`NoInferenceBackend`) ; le chemin structuré reste toujours disponible.

### Cibler un vrai OPNsense (interop)

L'agent OPNsense est un simple client de l'API REST OPNsense : pointe-le vers
l'API de n'importe quelle instance OPNsense sur son **interface LAN** et il
pilote le même jeu de fonctions canoniques. Le serveur d'agents lit :

| Variable              | Rôle                                                                     |
|-----------------------|--------------------------------------------------------------------------|
| `OPNSENSE_URL`        | URL de base de l'API sur le LAN, ex. `https://192.168.1.1` (un port non standard comme `:4443` convient) |
| `OPNSENSE_API_KEY`    | Clé API OPNsense                                                         |
| `OPNSENSE_API_SECRET` | Secret API OPNsense                                                      |
| `OPNSENSE_VERIFY_SSL` | `false` (défaut) accepte le certificat auto-signé de l'équipement ; `true` avec un certificat de confiance |

Expose l'API sur l'**interface LAN uniquement** (jamais le WAN), et autorise
l'hôte du serveur d'agents à joindre le port de l'API via une règle firewall
LAN. La joignabilité est contrôlée via `GET /api/core/system/status`.

**Besoin d'une VM cible ?** [`opnsense-ai-firewall`](https://gitlab.com/llm_tests/opnsense-ai-firewall)
(projet de lab) monte une VM OPNsense, et c'est aussi l'architecture *opposée*
à mettre en regard : il exécute le LLM **dans la boîte** (llama-server + LoRA
à l'intérieur du firewall, sans sidecar), et sa propre documentation mesure
pourquoi c'est un mauvais choix en production — surface d'attaque, contention
CPU, cycle de vie, audit. `cyber-agent-engine` est la réponse **externe** à
exactement ces quatre points : le LLM de raisonnement vit hors-boîte, donc le
firewall ne gagne ni surface d'attaque ni charge CPU ; le cycle de vie du
coordinateur est indépendant ; et chaque action passe par une politique
fail-closed, la tokenisation des PII, l'approbation humaine et un journal
d'audit borné. Pointe `OPNSENSE_URL` vers l'API LAN de cette VM (ex.
`https://<ip-lan>:4443` avec `OPNSENSE_VERIFY_SSL=false`) pour la piloter de
l'extérieur.

---

## Démarrage

### Tool-agent server

```bash
python server.py
```

Lance le serveur d'agents sur le port 3000. Le coordinateur y accède via `AGENT_SERVER_URL`.

### Dashboard (visualisation legacy)

```bash
uvicorn dashboard.app:app --port 8090
```

Le dashboard est une visualisation temps réel legacy, distincte de l'API du
coordinateur adossée à `core` ci-dessous. Ses routes d'approbation de
checkpoint (`POST /coordinator/checkpoint/{run_id}/approve` et `/reject`)
relaient vers un `COORDINATOR_URL` par défaut `http://localhost:3001` — l'API
coordinateur legacy, pas l'actuel `coordinator/app.py` (défaut `:8080`, voir
[API coordinateur](#api-coordinateur) ci-dessous). Lancer le dashboard sur un
port autre que 8080/3000/3001 pour éviter toute collision avec le
coordinateur et le serveur d'agents.

### Lancer le coordinateur

```bash
export COORDINATOR_API_KEY=...            # clé d'auth (obligatoire)
export COORDINATOR_SESSION_KEY=...        # clé Fernet base64 (obligatoire)
export COORDINATOR_POLICY_FILE=policy.yml # règles (obligatoire ; cf. policy.example.yml)
export AGENT_SERVER_URL=http://localhost:3000   # serveur d'agents
cyber-coordinator                          # lance uvicorn sur COORDINATOR_HOST:PORT (défaut 127.0.0.1:8080)
```

Le coordinateur refuse de démarrer si une variable obligatoire manque ou si
`policy.yml` est invalide (fail-closed). Copier `policy.example.yml` comme point
de départ. `GET /coordinator/health` sert la readiness (sans auth).

---

## API

### API coordinateur

Auth via `X-API-Key: <COORDINATOR_API_KEY>`, sauf `/coordinator/health`.

#### `POST /coordinator/execute`

Exécute une requête en langage naturel via la boucle gatée (proposer →
décider → suspendre ou exécuter). Corps : `{"request": "<texte>"}`. La
réponse est l'une de : `{"status": "completed", "summary": ..., "results": [...]}`,
`{"status": "pending_approval", "approval_id": "..."}`,
`{"status": "denied", "reason": "..."}`, ou
`{"status": "failed", "reason": "..."}`.

```bash
curl -X POST http://localhost:8080/coordinator/execute \
  -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"request": "ban IP 1.2.3.4 pour 24h"}'
```

#### `POST /coordinator/resume/{approval_id}`

Reprend une exécution suspendue après qu'un humain a approuvé l'action en attente.

```bash
curl -X POST http://localhost:8080/coordinator/resume/<approval_id> \
  -H "X-API-Key: <key>"
```

#### `POST /coordinator/reject/{approval_id}`

Rejette une approbation en attente ; l'exécution se termine `denied`, rien n'est exécuté.

```bash
curl -X POST http://localhost:8080/coordinator/reject/<approval_id> \
  -H "X-API-Key: <key>"
```

#### `GET /coordinator/health`

Sonde de disponibilité, sans auth : `{"status": "ok"}`.

### API du serveur d'agents

#### `GET /capabilities`

Découverte dynamique des fonctions disponibles. Nécessite `X-API-Key`. La
réponse porte aussi `server_version` et, par agent, `tool_name` en plus de
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
          "description": "Bloque une IP via un alias OPNsense.",
          "parameters": { "type": "object", "properties": { "ip": { "type": "string" } } }
        }
      ]
    }
  ]
}
```

#### `POST /agent/execute`

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

Avant toute action irréversible, `core.decide` renvoie `approve` : le
coordinateur suspend l'exécution et la persiste comme approbation en attente.
Un humain la reprend avec `POST /coordinator/resume/{approval_id}` (exécute)
ou la termine avec `POST /coordinator/reject/{approval_id}` (refuse, rien ne
s'exécute) — voir [API coordinateur](#api-coordinateur). Le dashboard legacy
offre les deux mêmes actions via son relais `:3001`. La durée de vie d'une
session suspendue est fixe à 300s (`session_ttl` dans `coordinator/loop.py`),
non configurable à ce jour via une variable d'environnement.

---

## Modèles publiés

Adapters LoRA fine-tunés sur **Qwen2.5-3B-Instruct**, entraînés avec Unsloth sur RTX 4070 Ti, publiés sur HuggingFace.

| Modèle | Fonctions | Score | Lien |
|---|---|---|---|
| OPNsense agent | 102 (firewall, NAT, IDS, IPsec, ACME, traffic shaping…) | 102/102 — 100% | [patlegu/opnsense-qwen25-lora](https://huggingface.co/patlegu/opnsense-qwen25-lora) |
| WireGuard agent | 11 (tunnels, peers, clés, routage) | 11/11 — 100% | [patlegu/wireguard-qwen25-lora](https://huggingface.co/patlegu/wireguard-qwen25-lora) |
| CrowdSec agent | 15 (bans, décisions, alertes, simulation) | 15/15 — 100% | [patlegu/crowdsec-qwen25-lora](https://huggingface.co/patlegu/crowdsec-qwen25-lora) |

Les 3 adapters partagent la même base — ils sont chargés simultanément par vLLM en **multi-LoRA dynamique** (swap à la volée sans recharger le backbone).

La vérification fonctionnelle exerce de bout en bout chaque fonction exposée
par le catalogue `GET /capabilities` de l'agent, contre l'API réelle de
l'équipement.

---

## Déploiement Docker

```bash
cp .env.example .env
# Générer la clé de session Fernet :
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Renseigner .env (COORDINATOR_API_KEY, COORDINATOR_SESSION_KEY, AGENT_API_KEY, backend LLM)
# Fournir une politique :
cp policy.example.yml policy.yml
docker compose up -d
curl http://localhost:8080/coordinator/health   # {"status":"ok"}
```

Le serveur d'agents n'est pas exposé sur l'hôte ; seul le coordinateur l'est. Le
coordinateur refuse de démarrer si une variable obligatoire manque ou si
`policy.yml` est invalide (fail-closed). Image GPU : override documenté (base CUDA
+ `pip install .[gpu]`), hors périmètre par défaut.

### Exploitation

- **Rétention de l'audit (disque borné)** : le log d'audit du coordinateur tourne
  par taille. Régler `COORDINATOR_AUDIT_MAX_BYTES` (défaut 100 Mio par fichier) et
  `COORDINATOR_AUDIT_BACKUPS` (défaut 5) ; l'usage disque est borné à environ
  `max_bytes × (backups + 1)`.
- **Plusieurs serveurs d'agents** : régler `AGENT_SERVERS` (URLs séparées par
  virgule, ex. `http://agent-a:3000,http://agent-b:3000`) pour router différents
  agents vers différents serveurs. Vide = le seul `AGENT_SERVER_URL`. Deux serveurs
  exposant le même nom d'agent → le coordinateur refuse de démarrer (routage
  ambigu).
- **Image GPU** : `docker build -f Dockerfile.gpu -t cyber-agent-engine:gpu .` pour
  servir les agents LoRA in-process (installe l'extra `[gpu]` : torch, vLLM,
  unsloth). L'image par défaut est CPU.
- **`policy.example.yml`** est fourni avec le dépôt source, pas avec le wheel pip —
  le copier depuis le dépôt (ou écrire le vôtre depuis le format ci-dessus).

### Releases & CI

- **CI** (`.github/workflows/ci.yml`) : à chaque push sur `main` et chaque pull
  request, lance ruff (surface source maintenue), mypy et la suite de tests.
- **Release** (`.github/workflows/release.yml`) : pousser un tag `v*` lance le gate
  de tests puis publie le sdist+wheel sur **PyPI** (Trusted Publishing / OIDC —
  aucun token stocké) et une image Docker CPU sur **GHCR**
  (`ghcr.io/patlegu/cyber-agent-engine:<tag>` + `:latest`).
- **Setup PyPI (une fois)** : créer un **Trusted Publisher** sur PyPI pour le projet
  `cyber-agent-engine` (propriétaire `patlegu`, dépôt `cyber-agent-engine`, workflow
  `release.yml`, environnement `pypi`). GHCR ne nécessite rien (`GITHUB_TOKEN`).
- **Couper une release** : aligner `[project].version` dans `pyproject.toml`, puis
  `git tag vX.Y.Z && git push origin vX.Y.Z` (le tag doit égaler la version, sinon
  le job de release échoue).
- L'image GHCR est la variante **CPU** ; l'image GPU est un build local
  (`Dockerfile.gpu`).

## Licence

Ce programme est un logiciel libre sous **AGPL-3.0-or-later** — voir [LICENSE](LICENSE).
Toute mise à disposition en service réseau doit s'accompagner de la publication du
code source modifié.
