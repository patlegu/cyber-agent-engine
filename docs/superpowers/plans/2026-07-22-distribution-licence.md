# Distribution & licence (D2) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre `cyber-agent-engine` distribuable et publiable par des tiers : licence AGPL-3.0, metadata pyproject complète (anglais), build wheel vérifié (fichiers de données embarqués), image Docker CPU + docker-compose de référence, documentation bilingue (README anglais canonique + français).

**Architecture:** Sous-projet packaging/docs/infra — presque pas de code applicatif (une seule addition : un endpoint `/health` non authentifié sur le serveur d'agents, requis par l'orchestration conteneur). Tout est vérifié par des tests déterministes ; le seul test « lourd » construit le wheel en local (sans isolation réseau) pour prouver que `agents/manifests/crowdsec.yml` y est embarqué.

**Tech Stack:** setuptools/PEP 621, `python -m build`, Docker (python:3.11-slim, multi-stage), docker-compose, pytest, tomllib, PyYAML.

## Global Constraints

- **CQI > 9, test-first.** Tests déterministes ; aucun `docker build`/`docker compose up` en test (validations statiques) ; un seul build wheel local (`--no-isolation`).
- **Licence : AGPL-3.0-or-later.** `LICENSE` = texte canonique FSF ; notice dans les deux READMEs ; expression SPDX dans pyproject. Pas d'en-têtes SPDX par fichier (→ D3).
- **Documentation utilisateur en anglais canonique** (`README.md`) + traduction française (`README.fr.md`), lien croisé en tête des deux. `description` pyproject en anglais. `.env.example` + doc Docker en anglais. **Les docstrings/commentaires de code restent en français** (convention gouvernante).
- **Correctness packaging** : `agents/manifests/crowdsec.yml` DOIT être dans le wheel (`load_manifest` en dépend au démarrage). Vérifié par test.
- **Aucun secret en clair** dans `.env.example`, le Dockerfile, le compose, les READMEs.
- **Non-régression** : les 149 tests A/B/C/D1 restent verts.
- **Commits** : `type(scope): sujet` minuscules, sans emoji, **sans** `Co-Authored-By`, **sans** mention d'IA.
- **DRY/YAGNI** : une seule image bi-rôle (commande fournie par compose) ; pas de publication réelle PyPI/GHCR (→ D3).

---

### Task 1 : Licence AGPL-3.0

**Files:**
- Create: `LICENSE`
- Test: `tests/test_license.py`

**Interfaces:** aucune (fichier + test).

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_license.py
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_license_file_present_and_agpl():
    text = (_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text
    assert "Version 3" in text
    # le texte canonique de l'AGPL fait ~660 lignes
    assert len(text.splitlines()) > 600
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_license.py -q`
Expected: FAIL (`LICENSE` absent).

- [ ] **Step 3 : Récupérer le texte canonique de l'AGPL-3.0**

Run:
```bash
curl -sSL --max-time 30 https://www.gnu.org/licenses/agpl-3.0.txt -o LICENSE
head -2 LICENSE && wc -l LICENSE
```
Expected: la 1ère ligne contient `GNU AFFERO GENERAL PUBLIC LICENSE` ; ~661 lignes. Si `curl` échoue (réseau), récupérer le même fichier via l'outil WebFetch sur la même URL et l'écrire dans `LICENSE`. Ne PAS écrire le texte de mémoire (risque d'inexactitude légale).

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `.venv/bin/pytest tests/test_license.py -q`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add LICENSE tests/test_license.py
git commit -m "chore: ajouter la licence AGPL-3.0"
```

---

### Task 2 : Metadata pyproject de publication

**Files:**
- Modify: `pyproject.toml` (`[project]` + `[project.urls]`)
- Test: `tests/test_project_metadata.py`

**Interfaces:**
- Produces: `[project]` avec `license = "AGPL-3.0-or-later"`, `authors`, `keywords`, `classifiers`, `description` (anglais), et `[project.urls]` Homepage/Repository/Issues.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_project_metadata.py
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _proj() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_license_is_agpl_spdx():
    assert _proj()["license"] == "AGPL-3.0-or-later"


def test_authors_present():
    authors = _proj()["authors"]
    assert authors and authors[0]["name"] and "@" in authors[0]["email"]


def test_urls_present():
    urls = _proj()["urls"]
    for key in ("Homepage", "Repository", "Issues"):
        assert key in urls and urls[key].startswith("https://")


def test_classifiers_include_agpl_and_security():
    joined = " ".join(_proj()["classifiers"])
    assert "Affero" in joined and "Topic :: Security" in joined


def test_description_is_current_not_factory():
    desc = _proj()["description"].lower()
    assert "factory" not in desc
    assert "coordinator" in desc or "security" in desc
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_project_metadata.py -q`
Expected: FAIL (`license`/`authors`/`urls`/classifiers absents ; description contient « factory »).

- [ ] **Step 3 : Compléter `[project]` dans `pyproject.toml`**

Remplacer la `description` et ajouter les champs manquants (garder `name`, `version`, `readme`, `requires-python`, `dependencies`, `[project.scripts]`, `[project.optional-dependencies]` existants) :

```toml
[project]
name = "cyber-agent-engine"
version = "1.0.0"
description = "Trust-cored multi-agent network-security coordinator (fail-closed policy, PII tokenization, human approval)"
readme = "README.md"
requires-python = ">=3.10"
license = "AGPL-3.0-or-later"
authors = [{ name = "patlegu", email = "patrice.leguyader@gmail.com" }]
keywords = ["security", "network", "llm-agents", "purple-team", "crowdsec", "opnsense", "wireguard"]
classifiers = [
    "Development Status :: 4 - Beta",
    "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)",
    "Programming Language :: Python :: 3.11",
    "Topic :: Security",
    "Intended Audience :: System Administrators",
]
dependencies = [
    "pydantic>=2.0.0",
    "httpx>=0.25.0",
    "pyyaml>=6.0",
    "jinja2>=3.0.0",
    "cryptography>=42.0.0",
    "fastapi>=0.110.0",
    "requests>=2.31.0",
    "anthropic>=0.40.0",
    "uvicorn>=0.30.0",
]

[project.urls]
Homepage = "https://github.com/patlegu/cyber-agent-engine"
Repository = "https://github.com/patlegu/cyber-agent-engine"
Issues = "https://github.com/patlegu/cyber-agent-engine/issues"
```

(Laisser `[project.scripts]` et `[project.optional-dependencies]` tels quels ; ne pas dupliquer.)

- [ ] **Step 4 : Lancer, vérifier le succès + réinstall editable**

Run: `.venv/bin/pytest tests/test_project_metadata.py -q && .venv/bin/pip install -e . >/dev/null 2>&1 && echo installed`
Expected: PASS ; `installed`. (Si `pip` refuse `license` en expression SPDX, vérifier `setuptools>=77` : `.venv/bin/pip install -U "setuptools>=77" >/dev/null 2>&1` puis réessayer — PEP 639 requiert setuptools récent.)

- [ ] **Step 5 : Commit**

```bash
git add pyproject.toml tests/test_project_metadata.py
git commit -m "chore(pyproject): metadata de publication (licence AGPL, authors, urls, classifiers)"
```

---

### Task 3 : Fichiers de données embarqués + build wheel vérifié

**Files:**
- Modify: `pyproject.toml` (`[tool.setuptools.package-data]`, extra `[dev]`)
- Create: `MANIFEST.in`
- Modify: `.gitignore` (dist/, build/, egg-info)
- Test: `tests/test_wheel_packaging.py`

**Interfaces:**
- Produces: le wheel embarque `agents/manifests/*.yml` ; extra `[dev]` avec `build`.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_wheel_packaging.py
import subprocess
import sys
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_wheel_embeds_manifest_and_packages(tmp_path: Path):
    # Build sans isolation (utilise le venv courant, pas de réseau).
    r = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(tmp_path), "."],
        cwd=str(_ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, r.stdout
    names = zipfile.ZipFile(wheels[0]).namelist()
    # fichier de données runtime critique
    assert any(n.endswith("agents/manifests/crowdsec.yml") for n in names), names[:20]
    # packages livrés
    for pkg in ("core/", "coordinator/", "agents/", "clients/"):
        assert any(n.startswith(pkg) for n in names), pkg
    # tests exclus du wheel
    assert not any(n.startswith("tests/") for n in names)
```

- [ ] **Step 2 : Installer `build` puis lancer, vérifier l'échec**

Run:
```bash
.venv/bin/pip install "build>=1.0" >/dev/null 2>&1
.venv/bin/pytest tests/test_wheel_packaging.py -q
```
Expected: FAIL (le manifeste n'est pas embarqué — pas de `package-data`).

- [ ] **Step 3 : Déclarer `package-data`, l'extra `[dev]`, et `MANIFEST.in`**

Dans `pyproject.toml`, sous la section setuptools, ajouter le bloc `package-data` :

```toml
[tool.setuptools.package-data]
agents = ["manifests/*.yml"]
```

Ajouter l'extra `[dev]` dans `[project.optional-dependencies]` (à côté de `gpu`) :

```toml
[project.optional-dependencies]
gpu = [
    "torch>=2.1.0",
    "vllm>=0.6.0",
    "unsloth",
]
dev = [
    "build>=1.0",
    "pytest>=8.0",
]
```

Créer `MANIFEST.in` (pour le sdist) :

```
include LICENSE
include README.md
include README.fr.md
include policy.example.yml
recursive-include agents/manifests *.yml
```

Ajouter à `.gitignore` (créer les lignes si absentes) :
```
dist/
build/
*.egg-info/
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `.venv/bin/pytest tests/test_wheel_packaging.py -q`
Expected: PASS (le wheel contient `agents/manifests/crowdsec.yml`, les 4 packages, et exclut `tests/`).

- [ ] **Step 5 : Commit**

```bash
git add pyproject.toml MANIFEST.in .gitignore tests/test_wheel_packaging.py
git commit -m "build: embarquer les manifestes dans le wheel, extra [dev], gitignore artefacts"
```

---

### Task 4 : Endpoint `/health` du serveur d'agents

**Files:**
- Modify: `server.py` (ajout d'une route `/health` non authentifiée)
- Test: `tests/agents/test_agent_server_health.py`

**Interfaces:**
- Produces: `GET /health` sur le serveur d'agents → `{"status": "ok"}`, **sans authentification** (pour le healthcheck conteneur et `depends_on: service_healthy` du compose).

Contexte : le serveur d'agents n'a pas d'endpoint de santé non authentifié (`/` renvoie un `FileResponse` vers `dashboard/templates/index.html`, absent de l'image slim → 500 ; `/capabilities` et `/api/status` exigent la clé). Le coordinateur, au démarrage, appelle `get_capabilities()` sur le serveur d'agents ; le compose doit donc pouvoir vérifier que le serveur d'agents est **healthy** avant de lancer le coordinateur.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/agents/test_agent_server_health.py
import importlib
from fastapi.testclient import TestClient


def test_health_no_auth(monkeypatch):
    monkeypatch.setenv("AGENT_API_KEY", "secret")
    import server
    importlib.reload(server)
    # TestClient sans context-manager ne lance pas le lifespan (pas d'init d'agents).
    client = TestClient(server.app)
    r = client.get("/health")  # aucune clé fournie
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/agents/test_agent_server_health.py -q`
Expected: FAIL (404, route absente).

- [ ] **Step 3 : Ajouter la route `/health` dans `server.py`**

Ajouter, à côté de la route `@app.get("/")` (ne PAS mettre de `dependencies=[Depends(verify_api_key)]` — la santé doit être publique) :

```python
@app.get("/health")
async def health() -> dict[str, str]:
    """Sonde de santé non authentifiée pour l'orchestration conteneur."""
    return {"status": "ok"}
```

- [ ] **Step 4 : Lancer, vérifier le succès + non-régression**

Run: `.venv/bin/pytest tests/agents/test_agent_server_health.py tests/agents/test_agent_server_structured.py -q`
Expected: PASS (le test structuré existant reste vert).

- [ ] **Step 5 : Commit**

```bash
git add server.py tests/agents/test_agent_server_health.py
git commit -m "feat(server): sonde /health non authentifiee pour l orchestration conteneur"
```

---

### Task 5 : Image Docker (CPU, non-root)

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Test: `tests/test_dockerfile.py`

**Interfaces:** aucune (image bi-rôle ; la commande vient du compose).

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_dockerfile.py
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_present_slim_multistage_nonroot():
    df = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.11-slim" in df
    assert "as builder" in df.lower()          # multi-stage
    assert "USER appuser" in df                 # non-root
    # aucun secret en dur : pas de ENV *_KEY=<valeur>
    import re
    assert not re.search(r'ENV\s+\w*(KEY|SECRET|TOKEN)\w*\s*=\s*\S+', df)


def test_dockerignore_excludes_heavy_paths():
    di = (_ROOT / ".dockerignore").read_text(encoding="utf-8")
    for path in (".venv", "tests", ".git", "dist"):
        assert path in di
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_dockerfile.py -q`
Expected: FAIL (`Dockerfile`/`.dockerignore` absents).

- [ ] **Step 3 : Créer `Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1
# Image bi-rôle (serveur d'agents OU coordinateur) — CPU, non-root.
# La commande réelle est fournie par docker-compose. GPU : override documenté.

FROM python:3.11-slim AS builder
WORKDIR /build
COPY pyproject.toml MANIFEST.in README.md ./
COPY core ./core
COPY coordinator ./coordinator
COPY agents ./agents
COPY clients ./clients
COPY server.py ./
RUN pip install --no-cache-dir --upgrade "setuptools>=77" wheel \
    && pip install --no-cache-dir --prefix=/install .

FROM python:3.11-slim AS runtime
# utilisateur non-root
RUN useradd --create-home --uid 10001 appuser
COPY --from=builder /install /usr/local
WORKDIR /app
COPY server.py ./
COPY dashboard ./dashboard
USER appuser
# CMD par défaut = coordinateur ; compose surcharge par service.
CMD ["cyber-coordinator"]
```

Note : on copie `server.py` et `dashboard/` dans le runtime car le serveur d'agents (`uvicorn server:app`) les référence ; le package installé (core/coordinator/agents/clients) vient de `/usr/local`. Aucun secret : tout par env/volumes au runtime.

- [ ] **Step 4 : Créer `.dockerignore`**

```
.venv
tests
docs
.git
.gitignore
dist
build
*.egg-info
__pycache__
*.pyc
.superpowers
.env
```

- [ ] **Step 5 : Lancer, vérifier le succès**

Run: `.venv/bin/pytest tests/test_dockerfile.py -q`
Expected: PASS.

- [ ] **Step 6 : Commit**

```bash
git add Dockerfile .dockerignore tests/test_dockerfile.py
git commit -m "build: image Docker CPU multi-stage non-root bi-role"
```

---

### Task 6 : `docker-compose.yml` de référence + `.env.example`

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Modify: `.gitignore` (`.env`)
- Test: `tests/test_compose.py`

**Interfaces:** aucune (infra).

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_compose.py
from pathlib import Path
import yaml

_ROOT = Path(__file__).resolve().parent.parent


def _compose() -> dict:
    return yaml.safe_load((_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_two_services_on_internal_network():
    c = _compose()
    assert set(("agent-server", "coordinator")).issubset(c["services"])
    assert c.get("networks")  # réseau défini


def test_agent_server_not_published_to_host():
    svc = _compose()["services"]["agent-server"]
    # pas de ports publiés sur l'hôte (isolé sur le réseau interne)
    assert "ports" not in svc or not svc["ports"]


def test_coordinator_publishes_and_depends_on_agent():
    svc = _compose()["services"]["coordinator"]
    assert svc.get("ports")  # exposé à l'opérateur
    assert "agent-server" in (svc.get("depends_on") or {})


def test_coordinator_healthcheck_and_persistence():
    c = _compose()
    coord = c["services"]["coordinator"]
    assert "healthcheck" in coord
    assert c.get("volumes")  # volumes nommés de persistance


def test_env_example_has_required_keys_no_secrets():
    env = (_ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ("COORDINATOR_API_KEY", "COORDINATOR_SESSION_KEY", "AGENT_API_KEY"):
        assert key in env
    # placeholders seulement : pas de valeur ressemblant à une vraie clé Fernet (44 chars b64)
    import re
    assert not re.search(r'=\s*[A-Za-z0-9_-]{40,}=*\s*$', env, re.MULTILINE)


def test_gitignore_excludes_env():
    assert ".env" in (_ROOT / ".gitignore").read_text(encoding="utf-8")
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_compose.py -q`
Expected: FAIL (`docker-compose.yml`/`.env.example` absents).

- [ ] **Step 3 : Créer `docker-compose.yml`**

```yaml
# docker-compose.yml — déploiement de référence (2 processus).
# Le serveur d'agents n'est PAS exposé à l'hôte ; seul le coordinateur l'est.
services:
  agent-server:
    build: .
    command: uvicorn server:app --host 0.0.0.0 --port 3000
    env_file: .env
    networks: [internal]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:3000/health').status==200 else 1)"]
      interval: 10s
      timeout: 5s
      retries: 5

  coordinator:
    build: .
    command: cyber-coordinator
    env_file: .env
    environment:
      AGENT_SERVER_URL: "http://agent-server:3000"
      COORDINATOR_HOST: "0.0.0.0"
      COORDINATOR_POLICY_FILE: "/policy/policy.yml"
      COORDINATOR_AUDIT_FILE: "/data/audit.jsonl"
      COORDINATOR_SESSION_DIR: "/data/sessions"
    ports:
      - "${COORDINATOR_PORT:-8080}:8080"
    volumes:
      - ./policy.yml:/policy/policy.yml:ro
      - coordinator-data:/data
    depends_on:
      agent-server:
        condition: service_healthy
    networks: [internal]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/coordinator/health').status==200 else 1)"]
      interval: 10s
      timeout: 5s
      retries: 5

networks:
  internal:
    driver: bridge

volumes:
  coordinator-data:
```

- [ ] **Step 4 : Créer `.env.example`** (anglais, aucune valeur réelle)

```bash
# .env.example — copy to .env and fill in. NEVER commit .env.
# Coordinator (operator-facing) auth key
COORDINATOR_API_KEY=change-me
# Fernet key for session encryption. Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
COORDINATOR_SESSION_KEY=change-me
# Host port the coordinator is published on
COORDINATOR_PORT=8080

# Agent server auth key (internal, coordinator -> agent-server)
AGENT_API_KEY=change-me

# Coordinator reasoning LLM backend (see README)
COORDINATOR_BACKEND=anthropic
ANTHROPIC_API_KEY=change-me
# Or an OpenAI-compatible endpoint:
# COORDINATOR_BACKEND=openai
# OPENAI_BASE_URL=https://openrouter.ai/api/v1
# OPENAI_API_KEY=change-me

# CrowdSec agent (optional; simulation mode if absent)
# CROWDSEC_URL=http://localhost:8080/v1
# CROWDSEC_API_KEY=change-me
```

- [ ] **Step 5 : Ajouter `.env` à `.gitignore`**

Ajouter la ligne `.env` à `.gitignore` (garder `.env.example` suivi).

- [ ] **Step 6 : Lancer, vérifier le succès**

Run: `.venv/bin/pytest tests/test_compose.py -q`
Expected: PASS.

- [ ] **Step 7 : Commit**

```bash
git add docker-compose.yml .env.example .gitignore tests/test_compose.py
git commit -m "build: docker-compose de reference (agent-server isole, coordinateur publie) + .env.example"
```

---

### Task 7 : Documentation bilingue (README.md EN canonique + README.fr.md)

**Files:**
- Create: `README.fr.md` (contenu français actuel + nouvelles sections + lien croisé)
- Modify: `README.md` (réécrit en anglais + nouvelles sections + lien croisé)
- Test: `tests/test_readme_bilingual.py`

**Interfaces:** aucune (docs).

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_readme_bilingual.py
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_both_readmes_exist():
    assert (_ROOT / "README.md").exists()
    assert (_ROOT / "README.fr.md").exists()


def test_cross_links():
    en = (_ROOT / "README.md").read_text(encoding="utf-8")
    fr = (_ROOT / "README.fr.md").read_text(encoding="utf-8")
    assert "README.fr.md" in en   # EN pointe vers FR
    assert "README.md" in fr      # FR pointe vers EN


def test_english_readme_markers():
    en = (_ROOT / "README.md").read_text(encoding="utf-8")
    # sections clés en anglais
    assert "Docker deployment" in en
    assert "License" in en and "AGPL" in en
    # pas de titre de section resté en français
    assert "## Démarrage" not in en


def test_french_readme_keeps_french_and_license():
    fr = (_ROOT / "README.fr.md").read_text(encoding="utf-8")
    assert "Licence" in fr and "AGPL" in fr
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_readme_bilingual.py -q`
Expected: FAIL (`README.fr.md` absent ; `README.md` encore en français).

- [ ] **Step 3 : Créer `README.fr.md`**

Copier le contenu actuel de `README.md` dans `README.fr.md`, ajouter en **toute première ligne** le lien croisé :

```markdown
*[English](README.md) · Français*
```

Puis ajouter, avant la fin du fichier, deux nouvelles sections en français :

````markdown
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

## Licence

Ce programme est un logiciel libre sous **AGPL-3.0-or-later** — voir [LICENSE](LICENSE).
Toute mise à disposition en service réseau doit s'accompagner de la publication du
code source modifié.
````

- [ ] **Step 4 : Réécrire `README.md` en anglais**

Réécrire `README.md` comme la **traduction anglaise fidèle** de `README.fr.md` : traduire chaque section de prose en anglais, **en conservant verbatim les blocs de code/commandes** (les commandes ne se traduisent pas), les noms de fichiers, les variables d'environnement et les liens. Mettre en première ligne le lien croisé :

```markdown
*English · [Français](README.fr.md)*
```

Traduire les titres de sections (« Architecture » → « Architecture », « Structure » → « Structure », « Stack » → « Stack », « Agents-outils » → « Tool agents », « Installation » → « Installation », « Configuration » → « Configuration », « Déploiement & backends » → « Deployment & backends », « Démarrage » → « Getting started », « API » → « API », « Décisions d'architecture » → « Architecture decisions », « Modèles publiés » → « Published models »). Ajouter les deux nouvelles sections en anglais :

````markdown
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
````

- [ ] **Step 5 : Lancer, vérifier le succès + non-régression complète**

Run: `.venv/bin/pytest tests/test_readme_bilingual.py -q && .venv/bin/pytest -q`
Expected: PASS ; suite complète verte.

- [ ] **Step 6 : Commit**

```bash
git add README.md README.fr.md tests/test_readme_bilingual.py
git commit -m "docs: README bilingue (anglais canonique + francais), sections Docker et licence"
```

---

## Auto-revue du plan (checklist auteur)

**Couverture du spec :**
- Chantier 1 (LICENSE AGPL) → Task 1. ✅
- Chantier 2 (metadata pyproject anglaise) → Task 2. ✅
- Chantier 3 (build wheel + data-files) → Task 3. ✅
- Chantier 4 (Docker image CPU non-root) → Task 5. ✅
- Chantier 5 (docker-compose + .env.example) → Task 6. ✅
- Chantier 6 (README bilingue EN/FR) → Task 7. ✅
- Sonde de santé requise par le compose (`depends_on: service_healthy`) → Task 4 (addition grounded : le serveur d'agents n'avait pas de `/health` non authentifié). ✅

**Raffinement du terrain (vs spec)** : ajout d'une route `/health` non authentifiée sur `server.py` (Task 4) — non explicitement dans le spec mais nécessaire pour le healthcheck de l'agent-server et le `depends_on: service_healthy` du coordinateur (le spec mentionnait « l'endpoint de santé » de l'agent-server sans qu'il existe). Justifié, minimal, testé.

**Cohérence** : `.env.example` (Task 6) référence les clés lues par `coordinator/config.py` (D1) et `server.py` ; le compose monte `policy.yml` et fixe `COORDINATOR_*` cohérents avec `load_config` ; le Dockerfile installe le paquet dont Task 3 garantit qu'il embarque les manifestes.

**Placeholders** : aucun code « à inventer ». La traduction du README (Task 7) est une génération de contenu explicitement cadrée (traduction fidèle, blocs de code verbatim, correspondance de titres fournie, nouvelles sections données mot pour mot) — pas un placeholder.

**Dette reportée (→ D3)** : publication réelle PyPI/GHCR + CI de release ; i18n des messages runtime ; en-têtes SPDX par fichier ; `Dockerfile.gpu` ; multi-tenant/ISM.
