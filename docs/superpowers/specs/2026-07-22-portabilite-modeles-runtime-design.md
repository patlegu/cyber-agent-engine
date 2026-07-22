# Design — Portabilité modèles & runtime (sous-projet C)

Date : 2026-07-22
Dépôt : `cyber-agent-engine` (public)
Statut : validé pour implémentation

## Contexte et cadrage

`cyber-agent-engine` est un coordinateur multi-agents de sécurité réseau. Les
sous-projets A (cœur de confiance) et B (contrat CAP v2 + bascule du coordinateur)
sont livrés et mergés. C rend le produit **déployable par des tiers sur des
backends variés** : API distante (OpenRouter/Anthropic/OpenAI-compatible),
llama.cpp CPU, Ollama, ou vLLM GPU — sans imposer GPU, `torch`, `unsloth`, ni le
paquet privé `factory`.

**Finalité (rappel A)** : produit déployable par des tiers, sécurité par défaut.
Décomposition :

- **A — Cœur de confiance & sûreté** *(livré)*.
- **B — Contrat CAP v2 & bascule du coordinateur** *(livré)*.
- **C — Portabilité modèles & runtime** *(ce spec)*.
- **D — Packaging de distribution, licence, exploitation, assemblage runtime,
  multi-tenant/isolation, ISM policy**.

### Découvertes de terrain qui cadrent C

1. **`factory` est un nom de paquet fantôme.** Le code importe partout
   `from factory.clients.X` et `from factory.agents.Y`, mais le paquet `factory`
   est **absent du dépôt** — un tiers ne peut ni importer ni lancer. Or les
   implémentations réelles existent déjà : dossier `clients/` à la racine
   (crowdsec, opnsense, wireguard, native_vllm, ollama…) et `agents/`. Le
   « découplage factory » est donc surtout une **correction de chemins d'import**
   (`factory.clients` → `clients`, `factory.agents` → `agents`), pas du vendoring.
2. **Une seule dépendance GPU.** Parmi les clients, seul
   `clients/native_vllm_client.py` importe `torch`+`vllm` au niveau module ; tous
   les autres sont légers (`httpx`/`requests`/`subprocess`). `unsloth` n'apparaît
   que dans `agents/base.py::_load_model` (déjà importé paresseusement). Le point
   dur : `TOOL_CALL_SCHEMA` vit dans `native_vllm_client.py`, donc l'importer
   tire torch.
3. **Le chemin de confiance de l'agent n'a besoin d'aucun modèle** (post-B :
   `execute_direct` → `_call_function`). L'appareillage SLM/LoRA de l'agent
   (`_infer_*`, `_load_model`, `vllm_client`, `ollama_client`) sert uniquement le
   chemin **NL** `execute()`, hors chemin de confiance.
4. **Les LoRA sont un actif public conservé.** Les LoRA opnsense/wireguard/crowdsec
   sont **publiés sur HuggingFace** (entraînement sur corpus privés, scripts en
   dépôts privés GitLab — hors périmètre). C **consomme** ces LoRA, ne les produit
   pas, et **préserve** la capacité NL par LoRA — mais la rend optionnelle et
   enfichable, jamais imposée.

### Ce que C ajoute vs retire

C **retire du couplage** et **isole les deps lourdes** ; il n'ajoute qu'un seul
composant (un backend d'inférence agent OpenAI-compatible). Après C :
`pip install cyber-agent-engine` + une clé API → coordinateur (backend API) +
agents structurés (`execute_direct`, sans modèle) tournent **sans GPU, torch,
unsloth ni factory**. Les agents LoRA NL et le loader in-process sont des extras
`[gpu]` optionnels.

## Contrainte gouvernante — CQI > 9 dès le départ

Qualité visée **> 9/10, à la conception**, livrée **test-first** : DAG de modules
sans cycle, feuilles pures, I/O injectée derrière interfaces, doubles
déterministes (aucun réseau), fail-closed à chaque frontière (dep manquante →
message clair, jamais d'`ImportError` brut). Commits `type(scope): sujet`
minuscules, sans emoji, sans `Co-Authored-By` ni mention d'IA. Docstrings en
français.

## Chantier 1 — Renommage des imports fantômes

- Remplacer partout `from factory.clients…` → `from clients…` et
  `from factory.agents…` → `from agents…` (agents, `base.py`,
  `coordinator/llm/coordinator_llm.py`, `server.py`, et les mentions résiduelles
  en docstrings/messages de dépréciation). `wireguard_agent.py` fait un
  `from factory.clients import WireGuardAPIClient, WireGuardLinuxClient` **sans**
  try/except — c'est ce qui casse aujourd'hui l'import du paquet `agents` ; le
  renommage le répare (les clients visés sont légers).
- Après correction, `python -c "import agents"` / `import clients` fonctionne
  **sans** aucun mock.

## Chantier 2 — Neutralisation de `TOOL_CALL_SCHEMA` et suppression du mock

- Déplacer `TOOL_CALL_SCHEMA` (un simple dict JSON-schema) de
  `clients/native_vllm_client.py` (qui tire torch) vers un module neutre
  `clients/tool_call_schema.py` (aucune dépendance). Mettre à jour les importeurs
  (`agents/base.py`, et `native_vllm_client.py` peut le ré-exporter pour
  compat). Importer `base.py` ne charge alors plus jamais torch.
- **Supprimer le mock `conftest.py`** (`sys.modules['factory'] = MagicMock()`) :
  inutile une fois les imports corrigés. Retirer aussi le shim local
  `factory.clients.native_vllm_client` dans
  `tests/agents/test_agent_server_structured.py` (base.py n'importe plus rien de
  lourd). La suite entière (99 tests B + nouveaux) doit rester verte via les
  **vrais** clients légers.

## Chantier 3 — Isolation de la dépendance GPU et extras pip

- **Import paresseux** : aucun `import torch`/`from vllm import …`/`import unsloth`
  au niveau module sur le chemin par défaut. `native_vllm_client.py` conserve ses
  imports lourds en tête (c'est son rôle), mais **personne ne l'importe au
  chargement** — seulement dans le corps des fonctions du loader in-process
  optionnel. `base.py::_load_model` garde son `try: from unsloth import …`
  paresseux et n'est jamais appelé par défaut.
- **`pyproject.toml`** :
  - **core** : `pydantic`, `httpx`, `pyyaml`, `cryptography`, `fastapi`,
    `requests`, `anthropic` — coordinateur (API) + agents structurés + clients
    d'appliance. Aucune dep ML.
  - **`[gpu]`** : `torch`, `vllm`, `unsloth` — loader in-process (agents LoRA
    locaux) + backend `vllm` in-process du coordinateur.
  - `[tool.setuptools.packages.find] include` : étendre de `["core*"]` à
    `["core*", "clients*", "agents*", "coordinator*"]` pour que `pip install`
    livre réellement le code.
- **Fail-safe `[gpu]` absent** : demander le loader in-process / backend vllm sans
  l'extra → **message d'erreur clair au démarrage** (« requiert l'extra `[gpu]` :
  pip install cyber-agent-engine[gpu] »), jamais un `ImportError` brut de torch.

## Chantier 4 — Backend d'inférence agent OpenAI-compatible (enfichable)

Seul ajout de code. `base.py::_infer_function` choisit aujourd'hui entre
`_infer_with_vllm` (in-process GPU) et `_infer_with_ollama`. On ajoute
`_infer_with_openai_compat`, **backend NL par défaut** quand un endpoint est
configuré.

- **Contrat** : POST `/v1/chat/completions` via `httpx`, `model = <nom du LoRA de
  l'outil>` (ex. `crowdsec-lora`). Le serveur (vLLM multi-LoRA, llama.cpp,
  Ollama `/v1`…) résout le LoRA. La réponse est parsée par le `_parse_model_output`
  **existant** — on ne touche qu'au transport, pas au parsing.
- **Sélection du backend agent** (au démarrage, fail-closed) :
  1. `AGENT_INFER_BASE_URL` configuré → `openai-compat` (défaut recommandé, sans
     dep lourde) ;
  2. sinon `ollama_config` présent → ollama ;
  3. sinon extra `[gpu]` + `vllm_client` fourni → in-process ;
  4. sinon **pas de chemin NL** : `execute()` renvoie une erreur explicite
     « aucun backend d'inférence configuré ». `execute_direct` (structuré) reste
     toujours disponible, sans modèle.
- **Configuration** : mapping outil→model via env (`AGENT_INFER_BASE_URL`,
  `AGENT_INFER_API_KEY`, `AGENT_LORA_MODELS` ou par agent
  `CROWDSEC_LORA_MODEL=…`). L'opérateur télécharge les LoRA de HF, les sert
  derrière l'endpoint, pointe l'agent dessus — rien d'in-process.
- **Injection & test** : transport HTTP injecté derrière une petite interface
  (comme `ChatLLM`), testé avec un faux client renvoyant un tool_call scripté ;
  aucun réseau. Vérifie le bon `FunctionCall` et la sélection déterministe/fail-
  closed. **YAGNI** : pas de client OpenAI complet — juste le POST nécessaire en
  httpx, réutilisant le parsing existant.

## Chantier 5 — Coordinateur : hygiène des backends

Frontière avec D : C rend le LLM du coordinateur **portable** ; l'assemblage
runtime complet de l'app **reste D**.

- `coordinator_llm.py` : import `native_vllm_client` rendu paresseux ; le backend
  `vllm` in-process ne charge torch **que** s'il est sélectionné et exige `[gpu]`
  (message clair sinon). `anthropic` et `openai` (couvrent OpenRouter, vLLM-HTTP,
  llama.cpp-server, Ollama `/v1`) restent sans dep lourde = voie par défaut.
- **Conformité au proposeur** : `LlmProposer` (B) attend `ChatLLM.chat(messages,
  max_tokens=1024) -> str` ; `CoordinatorLLM.chat` l'a déjà. Vérifié par test
  (structurel + appel via faux backend). Le câblage
  `LlmProposer(llm=CoordinatorLLM(), catalog=…)` est **documenté**, mais
  l'instanciation runtime réelle reste **D**.
- Aucun chemin du coordinateur n'impose de dep lourde ; le backend `vllm`
  in-process est conservé (option `[gpu]`) mais n'est plus défaut ni import au
  chargement. **Pas de réécriture de `create_default_app`** (→ D).

## Tests et qualité

Test-first, doubles déterministes, aucun réseau :

1. **Invariant de portabilité** (garde-fou clé) : sous-processus important
   `agents`, `coordinator.app`, `clients` — **échoue si `torch`/`vllm`/`unsloth`
   ∈ `sys.modules`**.
2. **Renommage** : `import agents` / `import clients` réussit sans mock ; suite
   entière verte après suppression du `conftest.py` mock.
3. **`TOOL_CALL_SCHEMA`** neutre : importable sans torch.
4. **Backend agent OpenAI-compatible** : faux transport → bon `FunctionCall` ;
   sélection de backend déterministe et fail-closed (endpoint absent → erreur
   claire, `execute_direct` toujours dispo).
5. **Fail-safe `[gpu]` absent** : loader in-process / backend vllm sans l'extra →
   message lisible (simulé en mockant l'échec d'import), pas d'`ImportError` brut.
6. **Conformité `CoordinatorLLM.chat` ↔ `ChatLLM`**.
7. **Non-régression B** : les 99 tests B restent verts via les vrais clients
   légers.

## Documentation de déploiement

Section README (fait partie de « déployable par des tiers ») :
`pip install cyber-agent-engine` (core) vs `[gpu]` ; variables de backend
coordinateur (`COORDINATOR_BACKEND`, `ANTHROPIC_API_KEY`, `OPENAI_BASE_URL`) ;
variables backend agent (`AGENT_INFER_BASE_URL`, `AGENT_LORA_MODELS`) ; comment
activer les agents LoRA (télécharger depuis HF, servir derrière un endpoint).
Aucun secret en clair.

## Dette reportée / hors périmètre

- Entraînement des LoRA (corpus/scripts, dépôts privés GitLab) — hors périmètre :
  C consomme les LoRA publics, ne les produit pas.
- Pruning éventuel de pfsense/stormshield — décision produit ultérieure ; C
  corrige seulement leurs imports.
- Assemblage runtime complet (`create_default_app`), licence, packaging de
  distribution, ISM, multi-tenant — **sous-projet D**.

## Hors périmètre

- Toute modification du contrat CAP v2 ou du cœur de confiance (A/B figés).
- Ajout de nouveaux agents-outils.
- Optimisation des modèles / fine-tuning.
