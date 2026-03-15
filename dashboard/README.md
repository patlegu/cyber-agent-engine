# Dashboard — Cyber Agent Engine

Interface web du coordinateur multi-agents.

## Architecture

```
dashboard/
├── app.py          ← API FastAPI (status système, proxy coordinateur, SSE)
├── templates/      ← ancien index.html statique (remplacé par frontend/dist)
├── static/         ← build Svelte généré par `npm run build` (servi par FastAPI)
└── frontend/       ← application Svelte (sources)
    ├── src/
    │   ├── App.svelte                       ← routing par tabs, connexion SSE au mount
    │   ├── lib/
    │   │   ├── components/
    │   │   │   ├── Header.svelte
    │   │   │   ├── Sidebar.svelte           ← nav : Chat / Tâches / Logs / État / À propos
    │   │   │   ├── ChatView.svelte          ← interface commandes coordinateur
    │   │   │   ├── AgentStatusView.svelte   ← tâches agents temps réel (depuis SSE)
    │   │   │   ├── SystemStatusView.svelte  ← CPU / RAM / réseau (polling 5s)
    │   │   │   └── NotificationDisplay.svelte
    │   │   ├── stores/
    │   │   │   ├── notificationStore.ts     ← notify(msg, type), auto-clear 5s
    │   │   │   ├── taskStore.ts             ← Task[], upsertTask()
    │   │   │   └── sidebarStore.ts
    │   │   └── utils/
    │   │       └── coordinatorApi.ts        ← connectSSE() + sendCommand()
    ├── package.json
    └── vite.config.ts                       ← proxy /api et /events → coordinateur :3001
```

## Stack frontend

- **Svelte 4** + TypeScript
- **Tailwind CSS 3** (dark mode `class`, thème zinc)
- **Vite 4** (build + dev server)
- Pas de Tauri — SPA web pure servie par FastAPI

## Test avec l'interface

Le stack complet nécessite **3 consoles**.

```
Console 1 — Tool-agent server (OPNsense / WireGuard / CrowdSec) — UDS socket
Console 2 — Coordinateur — port 3001  (vLLM chargé en interne au démarrage)
Console 3 — Dashboard FastAPI — port 8080
```

> **Mode dev frontend** : une 4e console optionnelle lance le serveur Vite (`:5173`)
> avec hot-reload au lieu de servir le build statique depuis FastAPI.

Le backend LLM (`COORDINATOR_BACKEND=vllm`) est instancié **en process** par le coordinateur via
`NativeVLLMClient` — aucun service LLM externe n'est requis. Le modèle se charge au démarrage du
coordinateur (quelques secondes selon la VRAM disponible).

Pour utiliser un autre backend, voir la section [Backends LLM](#backends-llm).

---

### Console 1 — Tool-agent server (UDS)

`server.py` est un **serveur monolithique** : il héberge les 3 agents (OPNsense, WireGuard, CrowdSec)
dans le même process, sur un seul socket Unix. Le coordinateur croit disposer de 3 serveurs séparés,
mais `WIREGUARD_AGENT_SOCK` et `CROWDSEC_AGENT_SOCK` pointent tous les deux vers le même socket que
`OPNSENSE_AGENT_SOCK` — le routage vers le bon agent se fait en interne par la classification de `server.py`.

Le chemin est défini par `UDS_SOCKET_PATH` dans `.env` (actuellement `/tmp/cyber-agents/opnsense.sock`).

```bash
cd /srv/cyber-agent-engine
source venv/bin/activate
source .env
python server.py
# → "Tool-agent server starting on UDS: /tmp/cyber-agents/opnsense.sock"
```

Vérification (curl avec socket Unix) :
```bash
curl --unix-socket /tmp/cyber-agents/opnsense.sock http://localhost/capabilities
```

> Si `UDS_SOCKET_PATH` n'est pas défini, le serveur bascule en TCP sur le port `TOOL_AGENT_PORT` (défaut: 3000) — fallback dev uniquement.

---

### Console 2 — Coordinateur (port 3001)

```bash
cd /srv/cyber-agent-engine
source venv/bin/activate
source .env
uvicorn coordinator.server:app --host 0.0.0.0 --port 3001
```

Au démarrage, le coordinateur charge le modèle vLLM (`Qwen/Qwen2.5-7B-Instruct` par défaut,
configurable via `COORDINATOR_MODEL`). La VRAM consommée dépend de `COORDINATOR_GPU_UTIL` (défaut: 0.5)
et `VLLM_MAX_MODEL_LEN` (défaut: 4096 dans le `.env` actuel).

Vérification : `curl http://localhost:3001/coordinator/health`

---

### Console 3 — Dashboard (port 8080)

```bash
cd /srv/cyber-agent-engine
source venv/bin/activate
source .env
uvicorn dashboard.app:app --host 0.0.0.0 --port 8080
```

Ouvrir : `http://localhost:8080`

---

### Console 4 (optionnel) — Dev frontend avec hot-reload

Utile pour modifier les composants Svelte sans rebuilder à chaque fois.
Le serveur Vite proxifie `/api` et `/events` directement vers le coordinateur sur `:3001`.

```bash
cd /srv/cyber-agent-engine/dashboard/frontend
npm run dev    # dev server sur :5173
```

Ouvrir : `http://localhost:5173` (à la place de `:8080`)

> Dans ce mode, `app.py` (port 8080) n'est **pas** nécessaire.
> Les consoles 1 et 2 restent requises.

---

### Ordre de démarrage recommandé

```
Tool-agent → Coordinateur → Dashboard
```

Le coordinateur tente de se connecter aux agents au démarrage (lifespan).
Si un agent est absent, il est ignoré avec un warning — le coordinateur démarre quand même.

---

### Backends LLM

Le backend est sélectionné par `COORDINATOR_BACKEND` dans `.env` :

| Backend | Variable clé | Remarque |
|---|---|---|
| `vllm` (défaut) | `COORDINATOR_MODEL`, `COORDINATOR_GPU_UTIL`, `VLLM_MAX_MODEL_LEN` | In-process, pas de service externe |
| `ollama` | `COORDINATOR_OLLAMA_MODEL` | Requiert `ollama serve` en amont (+1 console) |
| `anthropic` | `ANTHROPIC_API_KEY` | Pas de GPU requis, recommandé sans GPU |
| `openai` | `OPENAI_API_KEY`, `OPENAI_BASE_URL` | Compatible vLLM HTTP (port 8000) |

---

### Résumé des ports

| Service | Port | Commande de vérification |
|---|---|---|
| Tool-agent | 3000 | `curl http://localhost:3000/capabilities` |
| Coordinateur | 3001 | `curl http://localhost:3001/coordinator/health` |
| Dashboard | 8080 | `curl http://localhost:8080/api/status` |
| Vite (dev) | 5173 | `curl http://localhost:5173` |

---

## Pré-requis

Node.js **installé dans WSL/Linux** (pas la version Windows).

```bash
# Via nvm (recommandé)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 22 && nvm use 22
```

## Développement

```bash
cd dashboard/frontend
npm install
npm run dev        # dev server sur :5173, proxy /api et /events → :3001
```

Le coordinateur doit tourner sur le port 3001 (configurable via `.env`).

```bash
cp .env.example .env
# éditer VITE_COORDINATOR_URL si nécessaire
```

## Build production

```bash
cd dashboard/frontend
npm run build      # génère dashboard/static/
```

FastAPI sert ensuite `static/` en statique. Démarrer le dashboard :

```bash
cd /srv/cyber-agent-engine
source venv/bin/activate
uvicorn dashboard.app:app --port 8080
```

## API coordinateur attendue

Le frontend s'attend à deux routes côté coordinateur :

| Route | Méthode | Description |
|---|---|---|
| `/events` | `GET` (SSE) | Stream d'événements `task_update` et `notification` |
| `/api/command` | `POST` JSON `{ command }` | Envoie une commande, retourne `{ reply }` |
| `/api/status` | `GET` | Stats système (CPU, RAM, réseau, vLLM) |

### Format SSE

```json
{ "type": "task_update", "task": { "id": "...", "agent": "opnsense", "description": "...", "status": "running", "created_at": "..." } }
{ "type": "notification", "message": "...", "status": "success" }
```

---

## Roadmap — ce qui reste à faire

### Étape 1 — `app.py` : servir le build Svelte + stubs

- [x] Monter `static/` en StaticFiles dans FastAPI
- [x] Remplacer la route `/` → `templates/index.html` par → `static/index.html`
- [x] Ajouter un stub `POST /api/command` retournant `{ "reply": "..." }` (en attendant le coordinateur)
- [x] Ajouter un stub `GET /events` SSE (en attendant le coordinateur)

### Étape 2 — Build frontend

- [x] `npm run build` dans `dashboard/frontend/`
- [x] Vérifier que FastAPI sert correctement `static/index.html`
- [x] Vérifier l'UI dans le navigateur sur `:8080`

### Étape 3 — Transport agents ↔ coordinateur

Décision : **UDS + HTTP** (migration minimale, choix retenu).

- [x] Adapter `coordinator/clients/tool_agent_client.py` — transport httpx → UDS
- [x] Agents : uvicorn écoute sur socket fichier (`/run/agents/<agent>.sock`) au lieu d'un port TCP
- [x] Variables d'env `TOOL_AGENT_URL` remplacées par des chemins de socket

#### Alternative écartée pour l'instant : ZeroMQ

Raison du report : les agents sont déjà FastAPI/httpx, la migration UDS est non-destructive.
ZeroMQ devient pertinent si le besoin de **broadcast coordinateur → N agents** émerge (pub/sub),
ou si on veut du **pipeline** (fan-out de tâches parallèles sans bloquer).

Pattern ZeroMQ prévu si migration :
- Coordinateur : socket `DEALER` ou `PUB` sur `ipc:///run/agents/coordinator.ipc`
- Agents : socket `ROUTER`/`SUB` — s'enregistrent au démarrage
- `pip install pyzmq` côté Python
- Avantage : pas de serveur HTTP dans les agents, overhead minimal, patterns riches (REQ/REP, fan-out)

### Étape 4 — Coordinateur : route `/api/command`

- [x] Recevoir la commande texte de l'utilisateur
- [x] Classifier l'intention (quel agent, quelle action)
- [x] Déléguer à l'agent via le transport choisi (étape 3)
- [x] Retourner la réponse `{ "reply": "..." }`

### Étape 5 — Coordinateur : route `/events` SSE

- [x] Ouvrir un stream SSE par client connecté
- [x] Publier des `task_update` à chaque changement d'état d'une tâche agent
- [x] Publier des `notification` pour les erreurs et succès globaux

---

## Audit — bugs connus et points d'attention

### ~~Bug critique : routes checkpoint non relayées par `app.py`~~ — corrigé

`app.py` expose désormais `POST /coordinator/checkpoint/{run_id}/approve` et `/reject`
qui délèguent au coordinateur sur le même modèle que `/api/command`.

### ~~SSE sans heartbeat — risque de stream suspendu~~ — corrigé

Le relais SSE utilise maintenant `httpx.Timeout(read=20.0)` + boucle de reconnexion automatique.
En cas de silence du coordinateur → keepalive `": keepalive\n\n"` envoyé au client.
En cas d'exception → message d'erreur SSE + retry après 3 s.

### ~~Notifications SSE en boucle~~ — corrigé

`coordinatorApi.ts` utilise le store `sseStore.ts` (`SseState : connecting | connected | disconnected`).
Toast d'erreur affiché uniquement à la **première** déconnexion ; toast de succès à la reconnexion.
Les retries silencieux d'`EventSource` ne déclenchent plus de notification.

### ~~`scrollToBottom` avec `setTimeout(50ms)`~~ — corrigé

`ChatView.svelte` utilise désormais `await tick()` (import de `svelte`).

### Authentification — décision et roadmap

#### Choix actuel : pas d'auth (usage LAN mono-utilisateur)

Acceptable tant que le dashboard n'est accessible que sur le réseau local.
Si le dashboard doit être exposé, implémenter l'Option A ci-dessous.

---

#### ~~Option A — Bearer token statique~~ — implémenté

Mécanisme : token dans `.env`, vérifié par une dépendance FastAPI sur toutes les routes protégées.
`EventSource` ne supporte pas les headers custom → token passé en query param pour `/events`.

**`app.py`** — ajouter :

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_bearer = HTTPBearer(auto_error=False)
_DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN")

def require_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(default=None),   # fallback query param pour SSE
) -> None:
    if not _DASHBOARD_TOKEN:
        return  # auth désactivée si variable non définie (dev mode)
    provided = (creds.credentials if creds else None) or token
    if provided != _DASHBOARD_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide")
```

Appliquer la dépendance :

```python
@app.post("/api/command", dependencies=[Depends(require_auth)])
@app.post("/coordinator/checkpoint/{run_id}/approve", dependencies=[Depends(require_auth)])
@app.post("/coordinator/checkpoint/{run_id}/reject", dependencies=[Depends(require_auth)])
@app.get("/events", dependencies=[Depends(require_auth)])   # lit aussi ?token=
```

**`coordinatorApi.ts`** — passer le token dans les requêtes :

```ts
const TOKEN = import.meta.env.VITE_DASHBOARD_TOKEN || '';

// fetch → header Authorization: Bearer <token>
headers: { 'Content-Type': 'application/json', ...(TOKEN && { Authorization: `Bearer ${TOKEN}` }) }

// EventSource → query param
new EventSource(`${API_URL}/events${TOKEN ? `?token=${TOKEN}` : ''}`)
```

**`.env`** :
```
DASHBOARD_TOKEN=<secret généré avec openssl rand -hex 32>
VITE_DASHBOARD_TOKEN=<même secret>
```

---

#### Option B — Session cookie httpOnly ← à implémenter pour exposition internet / multi-utilisateurs

**Quand migrer** : dès qu'il y a plusieurs utilisateurs distincts, des rôles différents (lecture seule vs. approbation checkpoint), ou une exposition internet directe.

**Stack recommandée** :
- `fastapi-users` ou implémentation manuelle avec `itsdangerous.TimestampSigner`
- Cookie `httpOnly; Secure; SameSite=Strict` → transmis automatiquement par `EventSource` et `fetch`
- Pas de token en query param (plus sûr)
- Page de login Svelte (`/login`) → `POST /auth/login` → set cookie → redirect `/`
- Route `POST /auth/logout` → invalide le cookie

**Schéma de session** :

```
POST /auth/login   { username, password }
  → vérifie dans une table users (SQLite ou .htpasswd)
  → génère un token signé (JWT ou cookie signé itsdangerous, TTL 8h)
  → Set-Cookie: session=<token>; HttpOnly; Secure; SameSite=Strict

GET /api/*  /events  /coordinator/*
  → middleware vérifie le cookie session
  → 401 → redirect /login

POST /auth/logout
  → Set-Cookie: session=; Max-Age=0
```

**Gestion des rôles (optionnelle)** :

| Rôle | Permissions |
|---|---|
| `viewer` | lecture `/api/status`, `/events` |
| `operator` | + envoi commandes `/api/command` |
| `admin` | + approve/reject checkpoints |

**Points d'attention** :
- Renouveler le cookie avant expiration (sliding session ou refresh token)
- HTTPS obligatoire (flag `Secure` du cookie)
- Rotation du secret de signature si compromis
- Rate-limiting sur `POST /auth/login` (ex : `slowapi`)
