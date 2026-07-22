# Design — Assemblage runtime & configuration (sous-projet D1)

Date : 2026-07-22
Dépôt : `cyber-agent-engine` (public)
Statut : validé pour implémentation

## Contexte et cadrage

A (cœur de confiance), B (CAP v2 + bascule du coordinateur) et C (portabilité
modèles & runtime) sont livrés et mergés. Le produit est une **bibliothèque
testable** mais **pas encore lançable de bout en bout** : `create_default_app`
n'existe pas (retiré du périmètre en B), aucun `policy.yml` n'alimente le moteur
de politique, l'audit est en mémoire (`MemoryAuditSink`), et le câblage env→agent
d'inférence (C) est différé.

**Finalité (rappel A)** : produit déployable par des tiers. Le sous-projet **D**
(« finaliser la déployabilité ») est trop vaste pour un seul spec et se
décompose :

- **D1 — Assemblage runtime & configuration** *(ce spec)* : rendre le produit
  réellement lançable (coordinateur + serveur d'agents), config fail-closed,
  audit durable, câblage env→agent, + deux petites dettes repliées.
- **D2 — Distribution & licence** : LICENSE, metadata pyproject complète,
  build/publish (sdist/wheel), image Docker + compose de référence. Dépend de D1.
- **D3 — Isolation multi-tenant & durcissement exploitation** : namespaces par
  tenant (politique/vault/audit/session), rétention/ISM des logs, durcissement ops.

Ce spec ne couvre que **D1**.

### État constaté

- Aucune `LICENSE`, metadata pyproject minimale (→ D2).
- Aucun `policy.yml` ; le moteur `core.policy` existe mais rien ne l'alimente.
- Audit : `MemoryAuditSink` seulement (A notait « puits fichier → D »).
- Aucun `Dockerfile`/`compose`/`Makefile` (→ D2).
- Extracteur PII « réel » = spaCy (`agents/ner_extractor.py::NERExtractor`) —
  lourd, modèle à télécharger.
- `ToolAgent.__init__` accepte déjà `openai_client`/`lora_model` (C), non câblés
  depuis l'env.

## Contrainte gouvernante — CQI > 9 dès le départ

Test-first, DAG de modules sans cycle, feuilles pures composées par des
assembleurs minces, I/O injectée derrière interfaces, doubles déterministes
(aucun réseau, aucune horloge implicite dans le cœur), fail-closed lisible à
chaque frontière. Le **garde-fou d'import léger de C est maintenu** :
`create_default_app` ne doit importer aucune dep lourde au niveau module.
Commits `type(scope): sujet` minuscules, sans emoji, sans `Co-Authored-By` ni
mention d'IA. Docstrings en français.

## Architecture — deux assemblages runtime + trois feuilles neuves

Le produit a **deux processus** : le coordinateur et le serveur d'agents. D1
rend les deux lançables.

### Assemblages

- **Coordinateur** — `coordinator/app.py::create_default_app()` : lit la config
  (fail-closed), ouvre les `ToolAgentClient` par agent (env), construit le
  catalogue depuis leurs `get_capabilities()` live, charge `policy.yml` →
  `load_policy`, instancie `EncryptedFileSessionStore` + `FileAuditSink` +
  `ApprovalStore`, `LlmProposer(CoordinatorLLM())`, `make_agent_call(clients)`,
  l'extracteur regex, puis `GatedLoop` → `build_app`. Console script
  `cyber-coordinator` → uvicorn.
- **Serveur d'agents** — `server.py` (déjà assembleur) : D1 ajoute le **câblage
  env→agent** (construire un `OpenAICompatClient` depuis l'env, résoudre le
  `lora_model` par agent, les injecter dans chaque `ToolAgent`).

### Composants-feuilles neufs

- `coordinator/extractor.py` — extracteur PII **regex** (`ExtractFn`),
  déterministe, sans dep lourde.
- `core/audit/file_sink.py` — `FileAuditSink` : audit durable append-only JSONL,
  jetons uniquement.
- `coordinator/config.py` — chargement de config fail-closed (secrets, clés,
  chemins, endpoints agents).

Frontière : D1 assemble et rend lançable. Licence/distribution/Docker → D2 ;
multi-tenant/ISM → D3.

## Modèle de configuration

Deux surfaces : **env** (secrets/endpoints/chemins), **`policy.yml`** (règles).

### Variables d'environnement (`coordinator/config.py`, fail-closed sur les obligatoires)

| Variable | Rôle | Obligatoire |
|---|---|---|
| `COORDINATOR_API_KEY` | clé d'auth coordinateur (`core.auth`) | oui |
| `COORDINATOR_SESSION_KEY` | clé Fernet du `SessionStore` | oui |
| `COORDINATOR_POLICY_FILE` | chemin du `policy.yml` | oui |
| `COORDINATOR_AUDIT_FILE` | chemin JSONL d'audit | défaut `./audit.jsonl` |
| `COORDINATOR_SESSION_DIR` | dossier sessions chiffrées | défaut `./sessions` |
| `COORDINATOR_HOST` / `COORDINATOR_PORT` | bind uvicorn | défaut `127.0.0.1:8080` |
| `COORDINATOR_BACKEND` + clés LLM | backend proposeur (géré en C) | selon backend |
| `<AGENT>_AGENT_URL` / `_SOCK` / `_KEY` | endpoint par agent | ≥1 agent joignable |
| `AGENT_INFER_BASE_URL` / `_API_KEY` | endpoint NL des agents (serveur d'agents) | non |
| `<AGENT>_LORA_MODEL` / `AGENT_LORA_MODELS` | mapping outil→LoRA | non |

Fail-closed via les helpers existants (`load_auth_secret`, `load_session_key` /
`SessionKeyNotConfigured`) + messages clairs pour les chemins/endpoints.

### Format `policy.yml`

Liste de règles, ordre = priorité (première qui matche gagne, défaut deny) :

```yaml
# policy.yml
rules:
  - match: { capability: "crowdsec.get_*" }
    effect: allow
    reason: "lectures crowdsec sans risque"
  - match:
      capability: "crowdsec.ban_ip"
      args: { ip: { op: present } }
    effect: approve
    reason: "bannissement IP requiert validation"
  - match: { capability: "crowdsec.*" }
    effect: deny
```

Chargement : `config.py` lit le YAML → `raw_rules` → `load_policy(raw_rules,
catalog)` (de A : refuse le démarrage sur règle malformée ou glob ne couvrant
aucune capacité connue). Un `policy.example.yml` commité et documenté sert de
point de départ.

## Assemblage du coordinateur (`create_default_app`)

Fonction mince composant les feuilles A/B/C. **L'assemblage réseau (ouverture des
clients, catalogue live) se fait dans le `lifespan` FastAPI** (startup), pas au
niveau module — l'import de `coordinator.app` reste léger (invariant C) et un
échec de démarrage est propre et fail-closed.

```
create_default_app() -> FastAPI:
  # app créée synchronement ; câblage lourd au startup (lifespan)
  auth = load_auth_secret(env, "COORDINATOR_API_KEY")
  key  = load_session_key(env, "COORDINATOR_SESSION_KEY")
  # dans lifespan (async) :
  agents  = build_agent_clients(env)              # {nom: ToolAgentClient}, ≥1 requis
  live    = { nom: functions_of(await c.get_capabilities(), nom) for nom, c in agents }
  catalog = await build_catalog(list(agents), live)   # conformance C (drift → refus)
  policy  = load_policy(read_yaml(policy_file)["rules"], catalog)   # fail-closed
  loop = GatedLoop(
      proposer  = LlmProposer(llm=CoordinatorLLM(), catalog=catalog),
      catalog=catalog, policy=policy,
      sink      = FileAuditSink(audit_file),
      approvals = ApprovalStore(),
      sessions  = EncryptedFileSessionStore(session_dir, key),
      call      = make_agent_call(agents),
      extract   = build_regex_extractor(),
      clock     = time.time,
      id_factory= lambda: uuid4().hex,
  )
  # build_app(loop=loop, auth_secret=auth) monté sur l'app
```

- `build_agent_clients(env)` : un `ToolAgentClient` par agent depuis
  `<AGENT>_AGENT_URL`/`_SOCK`/`_KEY` (défaut socket UDS). Ouverts via
  `__aenter__` dans le lifespan, fermés à l'arrêt. ≥1 requis sinon refus.
- Catalogue au démarrage depuis `get_capabilities()` live ; conformance C
  s'applique (drift = refus de démarrer).
- `id_factory`/`clock` fournis à la frontière (uuid4, time.time) — le cœur reste
  pur.
- Point d'entrée : `[project.scripts] cyber-coordinator = "coordinator.app:run"`,
  `run()` lançant `uvicorn.run(...)` (host/port env). `/coordinator/health`
  existe déjà pour la readiness.

## Câblage env→agent (serveur d'agents)

Dette env→agent différée par C, réalisée dans le `lifespan` de `server.py` :

- Si `AGENT_INFER_BASE_URL` défini : construire un `OpenAICompatClient(base_url,
  api_key=AGENT_INFER_API_KEY)` **partagé** (le `model` discrimine les LoRA).
- `resolve_lora_models(env)` (helper déterministe) : `<AGENT>_LORA_MODEL` sinon
  `AGENT_LORA_MODELS="crowdsec=crowdsec-lora,..."`.
- Chaque agent construit avec `openai_client=<partagé ou None>` et
  `lora_model=<résolu>` (params existants de C — pur câblage).
- Endpoint absent → `openai_client=None` → sélection C (ollama/vllm si config,
  sinon `NoInferenceBackend` fail-closed) ; `execute_direct` toujours dispo.
- `OpenAICompatClient` (httpx) fermé au shutdown (`aclose()`).
- Les 3 agents reçoivent le câblage uniformément ; vérification fonctionnelle
  centrée CrowdSec.

## Composants-feuilles neufs

### `coordinator/extractor.py` — extracteur PII regex

- `build_regex_extractor() -> ExtractFn` : fonction pure appliquant un jeu de
  regex nommées, renvoyant `{label: [valeurs uniques, ordre stable]}`.
- Labels/patterns : `IP_ADDRESS` (IPv4 + IPv6 basique), `IP_SUBNET` (CIDR),
  `MAC_ADDRESS`, `HOSTNAME` (FQDN), `PORT_NUMBER`, `CVE` (`CVE-\d{4}-\d+`),
  `HASH` (md5/sha1/sha256 hex), `VPN_USER`/`SERVICE_ACCOUNT` (heuristique
  conservatrice), `SNMP_COMMUNITY` (motif contextuel).
- **Précision > rappel** calibrée pour ne pas sur-tokeniser le bruit ; matching
  le plus spécifique d'abord (CIDR avant IP). Chaque label testé isolément.
- spaCy `NERExtractor` reste dispo derrière l'extra `[ner]` via un
  `build_spacy_extractor()` optionnel (import paresseux), non câblé par défaut.

### `core/audit/file_sink.py` — `FileAuditSink`

- Implémente le `AuditSink` Protocol de A (`write(entry: AuditEntry) -> None`).
- Append-only JSONL : `entry.model_dump_json()` + `\n`, mode append, flush par
  écriture. Jetons uniquement (l'`AuditEntry` de A ne porte que des jetons).
- Chemin injecté (`COORDINATOR_AUDIT_FILE`), crée le dossier parent. Pas de
  rotation en D1 (→ D3/ISM).

## Dettes repliées

- **`rule_reason` à l'audit post-approbation** (dette A#3) : `resume`/`reject` de
  la boucle reconstruisent `Verdict(matched_rule=None)` → l'entrée
  `executed_after_approval`/`rejected` perd la règle. Fix : persister le
  `rule_reason` (ou la règle) dans la `SessionState`/l'`Approval` au suspend, et
  le réinjecter dans l'entrée d'audit à la reprise.
- **Uniformiser le no-silent-simulation** (dette C, revue F2) :
  `_infer_with_vllm`/`_infer_with_ollama`/`_infer_with_lora` retombent en
  `_infer_with_simulation` sur erreur runtime, alors que openai-compat et
  no-backend échouent franchement. Fix : ces trois chemins propagent l'erreur (ou
  renvoient un échec explicite) au lieu de simuler ; `_infer_with_simulation`
  subsiste seulement si explicitement activé (mode dev/CI).

## Tests et qualité

Test-first, doubles déterministes, aucun réseau/GPU :

1. **`config.py`** : fail-closed (secret/chemin manquant → message clair) ;
   parsing des endpoints agents.
2. **Extracteur regex** : chaque label isolé, unicité/ordre, non-sur-tokenisation.
3. **`FileAuditSink`** : round-trip JSONL, append, non-régression PII.
4. **`create_default_app`** : assemblage avec **faux clients d'agent**
   (get_capabilities/execute_structured scriptés), faux LLM, `tmp_path` pour
   session/audit ; `policy.yml` invalide → **refus de démarrer** ; agent
   injoignable géré ; **e2e assemblé** (requête→politique→approbation→reprise→
   audit) sans réseau ni GPU.
5. **Câblage env→agent** : `resolve_lora_models`, injection de
   l'`OpenAICompatClient` selon l'env.
6. **Dettes** : `rule_reason` présent dans l'audit post-approbation ; les 3
   chemins d'inférence ne simulent plus en silence.
7. **Non-régression** : les 114 tests A+B+C restent verts ; garde-fou d'import
   léger de C maintenu (`create_default_app` n'importe rien de lourd au niveau
   module — vérifié par `tests/test_portability.py`).

## Documentation

README : section « Lancer le coordinateur » (console script `cyber-coordinator`,
variables d'env obligatoires, `policy.example.yml`). Aucun secret en clair.

## Dette reportée / hors périmètre

- Distribution (LICENSE, metadata pyproject, sdist/wheel, Docker/compose) → **D2**.
- Multi-tenant, rétention/ISM des logs, rotation d'audit → **D3**.
- Entraînement des LoRA (dépôts privés) — hors périmètre global.

## Hors périmètre

- Modification du contrat CAP v2 ou du cœur de confiance (A/B figés, sauf la
  dette `rule_reason` explicitement repliée).
- Nouveaux agents-outils ou nouvelles capacités.
- Refonte du dashboard web (`dashboard/`).
