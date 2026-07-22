# Design — Distribution & licence (sous-projet D2)

Date : 2026-07-22
Dépôt : `cyber-agent-engine` (public)
Statut : validé pour implémentation

## Contexte et cadrage

A (cœur de confiance), B (CAP v2 + coordinateur), C (portabilité) et D1
(assemblage runtime) sont livrés et mergés : le produit se lance de bout en bout
(`cyber-coordinator` + serveur d'agents + clé API). D2 le rend **distribuable et
publiable par des tiers** : licence, metadata de publication, build vérifié,
image Docker + compose de référence, et une **surface de documentation
anglophone** (le dépôt vise l'adoption internationale).

**Finalité (rappel A)** : produit déployable par des tiers. Décomposition de D :

- **D1 — Assemblage runtime & configuration** *(livré)*.
- **D2 — Distribution & licence** *(ce spec)*.
- **D3 — Isolation multi-tenant & durcissement exploitation** : namespaces par
  tenant, rétention/ISM des logs, rotation d'audit, multi-serveur d'agents, CI de
  release, en-têtes SPDX par fichier. Après D2.

### État constaté

- **Aucune `LICENSE`** (bloquant pour publier).
- Metadata pyproject minimale/périmée : `description` parle encore de « factory
  LoRA » ; pas d'`authors`/`license`/`classifiers`/`urls`. Version 1.0.0.
- **Aucun Docker/compose**.
- README unique **en français** ; un `dashboard/EN_README.md` existe mais est
  spécifique au dashboard et périmé (hors périmètre D2).
- Fichiers de données runtime à embarquer : `agents/manifests/crowdsec.yml`
  (chargé par `load_manifest` au démarrage), `policy.example.yml`.
- Auteur git : `patlegu <patrice.leguyader@gmail.com>`.

## Contrainte gouvernante — CQI > 9 dès le départ

Tests déterministes (sans lancer Docker sauf le build wheel unique), non-régression
des 149 tests A/B/C/D1. Commits `type(scope): sujet` minuscules, sans emoji, sans
`Co-Authored-By` ni mention d'IA. **Docstrings/commentaires de code en français**
(convention gouvernante inchangée) ; la **documentation utilisateur** (README,
description, doc de déploiement, `.env.example`) est **anglaise canonique** +
traduction française.

## Décisions actées

- **Licence : AGPL-3.0-or-later** (copyleft réseau — cohérent avec l'éthos
  souveraineté/anti-SaaS ; empêche la SaaS-ification fermée).
- **README anglais canonique** : `README.md` en anglais (affiché par défaut par
  GitHub/PyPI, audience internationale) ; le contenu français actuel déménage en
  `README.fr.md` ; lien croisé en tête des deux.

## Chantier 1 — Licence AGPL-3.0

- **`LICENSE`** à la racine : texte intégral canonique de l'AGPL-3.0 (FSF).
- **Notice** dans les deux READMEs (§ licence : « free software under AGPL-3.0,
  see LICENSE ») et référence dans la metadata pyproject.
- **Pas d'en-têtes SPDX par fichier** en D2 (churn 100+ fichiers, bénéfice
  marginal ; → D3 si souhaité). La licence dépôt (fichier + metadata + notice)
  suffit juridiquement.

## Chantier 2 — Metadata pyproject de publication

Le bloc `[project]` complété (anglais, produit réel) :

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

[project.urls]
Homepage = "https://github.com/patlegu/cyber-agent-engine"
Repository = "https://github.com/patlegu/cyber-agent-engine"
Issues = "https://github.com/patlegu/cyber-agent-engine/issues"
```

- `license` en expression SPDX (PEP 639), pas la table `{file=...}` dépréciée.
- `description` réécrite (anglais) pour refléter le coordinateur de confiance, pas
  l'ancienne factory. Version 1.0.0 conservée (bump = décision produit hors D2).

## Chantier 3 — Build sdist/wheel & fichiers de données

Point de correctness : les **fichiers de données runtime** doivent être livrés
dans le wheel, sinon l'install pip casse à l'exécution.

- **`[tool.setuptools.package-data]`** : `"agents" = ["manifests/*.yml"]` — les
  manifestes YAML sont *dans* le package `agents`, donc livrés avec le wheel. Sans
  ça, `create_default_app` échoue (`load_manifest` ne trouve pas
  `crowdsec.yml`).
- **`policy.example.yml`** (racine, hors package) : livré dans le **sdist** via
  `MANIFEST.in` ; non requis dans le wheel (exemple, pas du code).
- **Build** : `python -m build` → `dist/*.whl` + `dist/*.tar.gz`.
- **`.gitignore`** : `dist/`, `build/`, `*.egg-info/`.

## Chantier 4 — Image Docker (CPU, non-root)

Un seul `Dockerfile` pour les deux processus (même code, commande différente).

- **Base** `python:3.11-slim`, **multi-stage** (builder installe le paquet + deps
  core sans `[gpu]` ; runtime mince).
- **Non-root** : utilisateur dédié `appuser`, `WORKDIR /app`, aucun secret dans
  l'image (env/volumes au runtime).
- **Contenu** : `pip install .` (pas d'extras GPU). Pas d'`ENTRYPOINT` figé (image
  bi-rôle) ; `CMD` par défaut = coordinateur ; la commande réelle vient du compose.
- **`.dockerignore`** : `.venv/`, `tests/`, `docs/`, `.git/`, `dist/`,
  `__pycache__/`.
- **GPU** : override documenté (base CUDA + `.[gpu]`) — hors périmètre D2, note
  seulement ; l'image par défaut est CPU.

## Chantier 5 — `docker-compose.yml` de référence

Topologie 2 processus, `docker compose up` prêt, défauts sûrs.

- **Services** sur un **réseau interne** dédié :
  - `agent-server` : `command: uvicorn server:app --host 0.0.0.0 --port 3000` ;
    **pas de port publié sur l'hôte** ; auth `AGENT_API_KEY`.
  - `coordinator` : `command: cyber-coordinator` ;
    `AGENT_SERVER_URL=http://agent-server:3000` ; **publie** `COORDINATOR_PORT`
    sur l'hôte (point d'entrée opérateur) ; `depends_on: agent-server`.
- **Communication** : TCP sur le réseau interne compose (le serveur d'agents n'est
  pas exposé à l'hôte ; seul le coordinateur l'est) ; l'auth `AGENT_API_KEY`
  protège l'appel interne. UDS via volume partagé documenté mais pas le défaut.
- **Config** : fichier **`.env`** (chargé par compose) — `COORDINATOR_API_KEY`,
  `COORDINATOR_SESSION_KEY`, `AGENT_API_KEY`, `CROWDSEC_*`, backend LLM, etc. Un
  **`.env.example`** commité (anglais, **sans valeurs réelles**) ; `.env` en
  `.gitignore`.
- **Persistance** : volumes nommés pour `COORDINATOR_SESSION_DIR` (sessions
  chiffrées) et `COORDINATOR_AUDIT_FILE` (audit JSONL) ; `policy.yml` monté en
  lecture seule depuis l'hôte.
- **Healthchecks** : `coordinator` → `GET /coordinator/health` ; `restart:
  unless-stopped`.
- **Fail-closed** : secrets/politique manquants → le coordinateur refuse de
  démarrer (D1) → crash-loop visible plutôt qu'ouvert.

## Chantier 6 — Documentation bilingue

- **`README.md` (anglais canonique)** : traduction du contenu actuel (intro,
  config, démarrage, backends, lancement du coordinateur) + **nouvelle section
  « Docker deployment »** (cp .env.example .env, génération de
  `COORDINATOR_SESSION_KEY` via `python -c "from cryptography.fernet import
  Fernet; print(Fernet.generate_key().decode())"`, montage de `policy.yml`,
  `docker compose up -d`, check `/coordinator/health`, note GPU) + **notice
  licence AGPL**. Lien « Français » vers `README.fr.md` en tête.
- **`README.fr.md`** : contenu français actuel déplacé + les mêmes nouvelles
  sections (Docker, licence) en français. Lien « English » vers `README.md` en
  tête.
- Le `dashboard/EN_README.md` existant (spécifique dashboard, périmé) reste hors
  périmètre.

## Tests et qualité

Déterministes, sans lancer Docker (sauf le build wheel unique) :

1. **Metadata pyproject** (`tomllib`) : `license == "AGPL-3.0-or-later"` ;
   `authors` présent ; `urls` (Homepage/Repository/Issues) ; classifiers incluant
   l'AGPL et `Topic :: Security` ; `description` ne contient plus « factory ».
2. **`LICENSE`** : présent, contient « GNU AFFERO GENERAL PUBLIC LICENSE » et
   « Version 3 ».
3. **Wheel** : `python -m build --wheel` dans un tmp → le zip contient
   `agents/manifests/crowdsec.yml` et les packages `core/coordinator/agents/
   clients` ; **exclut** `tests/`. (Garde-fou anti-wheel-cassé.)
4. **`docker-compose.yml`** : YAML valide ; services `agent-server` +
   `coordinator` ; réseau interne ; volumes de persistance ; healthcheck
   coordinateur ; l'agent-server **ne publie pas** de port hôte ; le coordinateur
   publie son port.
5. **`.env.example`** : présent, référence les clés obligatoires, **aucune valeur
   secrète réelle**.
6. **READMEs bilingues** : `README.md` et `README.fr.md` présents ; chacun
   contient le lien croisé vers l'autre ; `README.md` (anglais) contient les
   sections clés (Docker deployment, license/AGPL) et est en anglais (heuristique :
   présence de marqueurs anglais, absence de titres français comme « Démarrage »
   au profit de « Getting started »/« Deployment »).
7. **Non-régression** : les 149 tests A/B/C/D1 restent verts.

## Dette reportée / hors périmètre

- **Publication réelle** sur PyPI/GHCR + CI de release → **D3** (D2 vérifie le
  build localement, ne publie pas).
- **i18n des messages runtime** (erreurs/CLI en anglais) — chantier séparé, hors
  D2 (la surface de distribution anglophone suffit à « suivre/déployer »).
- En-têtes SPDX par fichier, `Dockerfile.gpu`, multi-serveur d'agents, multi-tenant
  → **D3**.

## Hors périmètre

- Modification du code applicatif A/B/C/D1 (D2 est packaging/docs/infra).
- Refonte du dashboard web.
