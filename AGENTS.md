# AGENTS.md — Cyber Agent Engine Specialist

Bienvenue dans `cyber-agent-engine`. Ce document est le manuel de référence pour tout agent IA (coordinateur, agent de code) qui doit opérer, faire évoluer ou déboguer ce moteur.

---

## Règle de mise à jour de la documentation

**Tout agent de développement doit maintenir `AGENTS.md` et `README.md` à jour après chaque travail significatif.**

| Fichier | Audience | Contenu à y tenir à jour |
| --- | --- | --- |
| `AGENTS.md` | Agents IA, développeurs avancés | Architecture interne, règles de développement, gotchas techniques, décisions d'architecture, contrats d'interface (schémas, erreurs) |
| `README.md` | Humains, nouveaux arrivants | Installation, API HTTP, configuration, scripts disponibles, décisions d'architecture visibles depuis l'extérieur |
| `JOURNAL.md` | Équipe, agents IA | Résultats chiffrés d'entraînement, apprentissages ML, décisions techniques avec date |

### Mode brainstorming / échange

Quand une session de travail prend la forme d'un échange de réflexions (conception, arbitrage d'architecture, exploration d'options), **les deux parties de la réflexion doivent être enregistrées** — pas seulement la conclusion.

Cela s'applique aux fichiers roadmap (`roadmaps/*.md`) :
- Les réflexions de l'agent (options envisagées, arbitrages, recommandations) sont loggées dans le fichier concerné **au moment où elles sont produites**, sans attendre une décision finale.
- Les prises de position du responsable (contraintes métier, choix confirmés, cas d'usage précisés) sont loggées de la même façon.
- L'objectif : le fichier roadmap devient la mémoire vivante du raisonnement, pas seulement un résultat.

**Ménage des fichiers roadmap**

Les fichiers roadmap peuvent accumuler des entrées redondantes ou dépassées. Un nettoyage peut être déclenché :
- Par le responsable, à tout moment.
- Par l'agent, s'il identifie des contradictions ou redondances — **mais uniquement après validation explicite du responsable avant toute modification**.

L'agent ne nettoie jamais un fichier roadmap de sa propre initiative sans accord préalable.

### Quand mettre à jour

- **Nouvel agent ou nouveau mixin** → mettre à jour le catalogue agents dans `AGENTS.md` + le tableau `Architecture` dans `README.md`
- **Nouvelle fonction exposée** → vérifier que la checklist documentation est respectée (section "Documentation des fonctions" ci-dessous)
- **Nouveau script** → ajouter une ligne dans la section `Scripts factory/scripts/` de `README.md`
- **Nouvelle variable d'environnement** → l'ajouter dans les sections Configuration de `README.md` et Variables d'environnement de `AGENTS.md`
- **Nouvelle route API** → documenter dans `README.md` (section API) et `AGENTS.md` (section Auth si protégée)
- **Décision d'architecture** → consigner dans `AGENTS.md` (section Architecture) **et** `README.md` (section Décisions d'architecture) si elle concerne l'organisation du code
- **Gotcha ou bug non-évident résolu** → ajouter dans la section "Gotchas de développement" de `AGENTS.md`
- **Run d'entraînement terminé** → enregistrer dans `JOURNAL.md` (paramètres, loss, durée, observations, prochaines actions)

Les deux fichiers doivent rester cohérents entre eux. En cas de contradiction, `AGENTS.md` fait référence pour les détails techniques.

---

## Rôle du serveur

Ce serveur est un **agent-outil** (`tool agent`), pas un agent conversationnel.
Il est conçu pour être appelé par un agent coordinateur/raisonnant (LangGraph, CrewAI, AutoGen…).
Il exécute des actions concrètes sur des équipements réseau en interprétant du langage naturel.

---

## Architecture & "Mental Model"

### 1. Core Agent (`agents/base.py`)

Fichier le plus critique. Définit `ToolAgent`, qui fournit :

- **Fuzzy Matching avec cache** : correspondance souple des noms de fonctions via `SequenceMatcher`.
  Le résultat est mis en cache par instance (`_function_resolution_cache`) pour éviter les recalculs.
  Pénalité -0.8 sur les correspondances cross-catégorie (ADD ↔ DEL) — jamais de confusion "block/unblock".
- **Mandatory Argument Guard** : valide que tous les arguments positionnels sans défaut sont présents dans le JSON du LLM avant appel.
- **Multi-LoRA Switching** : bascule entre les adaptateurs (`opnsense`, `wireguard`) via le singleton `NativeVLLMClient`.
- **Structured Error Codes** : chaque échec retourne un `ErrorCode` (voir `agents/errors.py`) permettant au coordinateur de décider retry/fallback/escalade.
- **`get_capabilities()`** : introspection de `_functions` via `inspect.signature()` + docstrings → liste de schémas OpenAI function-calling. Déduplique automatiquement les alias (même callable → un seul schéma avec champ `aliases`).

### 2. Routage d'intention (`agents/classifier.py`)

`AgentClassifier` attribue un score pondéré à chaque agent via des mots-clés à 4 niveaux :

```text
strong (+1.0) / medium (+0.5) / weak (+0.2) / negative (−1.0)
```

Retourne `(agent_name, confidence)`. Le serveur construit une liste de priorité : l'agent avec le meilleur score est testé en premier, puis les autres en fallback.

> Règle : si un agent identifie la fonction (même en échec d'exécution), le fallback s'arrête — on ne laisse pas un autre agent halluciner.

### 3. Codes d'erreur structurés (`agents/errors.py`)

`ToolResult.error_code` permet au coordinateur de prendre des décisions :

| `ErrorCode` | Cause | Action coordinateur |
| --- | --- | --- |
| `FUNCTION_UNKNOWN` | Aucune fonction reconnue | Reformuler ou escalader |
| `MISSING_ARG` | Argument obligatoire absent | Demander l'info à l'utilisateur |
| `EXECUTION_ERROR` | Exception imprévue | Logger et escalader |
| `API_UNREACHABLE` | Timeout / refus de connexion | Retry avec backoff |
| `PERMISSION_DENIED` | HTTP 401/403 équipement | Escalader à l'opérateur humain |
| `INFERENCE_FAILED` | vLLM/Ollama en erreur | Basculer sur simulation |

### 4. Déploiement CPU — export ONNX du LoRA fine-tuné (réflexion 2026-02-27)

Le modèle de base Phi-3.5-mini-instruct existe en version ONNX officielle (`microsoft/Phi-3.5-mini-instruct-onnx`). ONNX est un **format d'inférence uniquement** — l'entraînement LoRA reste en HuggingFace/PyTorch sur GPU. Mais une fois l'adapter entraîné, on peut merger et exporter pour une inférence CPU-only.

**Pipeline GPU → CPU :**

```
train_opnsense_lora.py        merge_and_export.py          inférence
(GPU, HF LoRA)          →     (GPU, une seule fois)   →    (CPU, onnxruntime-genai)
                               PeftModel.merge_and_unload()
                               + optimum-cli export onnx
                               + quantization int4
```

**Ce que ça change pour le déploiement :**

| | Actuel (HF + LoRA) | Après export ONNX |
|---|---|---|
| GPU requis à l'inférence | oui (~6 Go VRAM) | non |
| RAM inférence | ~6 Go | ~2.5 Go |
| Dépendances runtime | torch, transformers, peft | `onnxruntime-genai` uniquement |
| Déploiement | serveur GPU dédié | VM légère, NAS, machine quelconque |
| LoRA swapping dynamique | oui (multi-LoRA) | non (modèle merged statique) |

**Microsoft Olive** est l'outil Microsoft pour automatiser ce pipeline (finetune → merge → quantize → ONNX) en une seule config JSON.

**Limites :** le LoRA swapping dynamique (basculer entre opnsense/wireguard à la volée) n't est pas possible avec un modèle ONNX merged — il faudrait un modèle ONNX par agent. Acceptable si les agents sont déployés séparément.

**Statut :** piste à explorer après validation du run v3 (score ≥ 93%). Priorité basse tant que le serveur GPU est disponible.

### 5. Inférence haute performance (`factory/clients/native_vllm_client.py`)

- **Singleton** : un seul `NativeVLLMClient` pour éviter la fragmentation VRAM.
- **Quantization** : 8 bits (`bitsandbytes`).
- **Contexte** : `VLLM_MAX_MODEL_LEN` (défaut 2048, réduire à 1024 si VRAM < 8 Go).
- **GPU utilization** : 0.6 en mode serveur (conservateur).
- **Shutdown** : appeler **obligatoirement** `vllm_client.shutdown()` à l'arrêt pour libérer le cache CUDA. Un oubli provoque des fuites mémoire au redémarrage.
- **Thread safety** : `generate()` est bloquant. Il est wrappé dans `loop.run_in_executor(None, ...)` — ne jamais l'appeler directement dans une coroutine `async`.

#### Structured Output (`TOOL_CALL_SCHEMA` + `StructuredOutputsParams`)

`TOOL_CALL_SCHEMA` est un schéma JSON strict qui force le SLM à produire un tableau d'appels valides :

```python
TOOL_CALL_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "arguments": {"type": "object"}
        },
        "required": ["name", "arguments"]
    },
    "minItems": 1, "maxItems": 1
}
```

`complete()` accepte un `json_schema` optionnel. Si vLLM ≥ 0.15.0 et `StructuredOutputsParams` disponible, il est injecté dans `SamplingParams` → l'engine Outlines/xgrammar contraint les tokens générés. En cas d'échec (ex: bitsandbytes + `enforce_eager` incompatible), le fallback silencieux revient à la génération libre + regex parser.

`agents/base.py` passe `json_schema=TOOL_CALL_SCHEMA` à chaque appel `_infer_with_vllm()`. **Ne pas retirer ce paramètre** — le regex parser reste en dernier recours mais est moins robuste.

Le log `"Structured output failed"` indique que le fallback est actif.

### 5. Package OPNsense (`agents/opnsense/`)

L'agent OPNsense est découpé en mixins par domaine fonctionnel :

```text
_base.py        OPNsenseAgent — hérite de tous les mixins + ToolAgent
_filters.py     FilterRulesMixin    — 6 méthodes (CRUD règles firewall)
_aliases.py     AliasesMixin        — 10 méthodes (alias IP/réseau/port)
_nat.py         NATMixin            — 5 méthodes (port-forward, outbound NAT)
_diagnostics.py DiagnosticsMixin    — 7 méthodes (ping, traceroute, logs)
_config.py      ConfigMixin         — 9 méthodes (backup/restore, reconfigure)
_extended.py    ExtendedMixin       — 14 méthodes (GeoIP, firmware, DNS, DHCP)
_legacy.py      LegacyMixin         — block_ip / unblock_ip (compat ascendante)
_decorators.py  @safety_snapshot
```

Import backward-compatible : `from agents.opnsense_agent import OPNsenseAgent` fonctionne toujours.

**Ordre MRO** : `OPNsenseAgent` doit appeler `super().__init__()` **après** avoir initialisé `self.platform` et `self._api_client`, car `_register_functions()` y fait référence lors de l'init de `ToolAgent`.

**Quand créer des mixins pour un nouvel agent ?** Uniquement si l'agent dépasse **~15-20 fonctions propres** réparties sur des domaines fonctionnels distincts. En dessous de ce seuil, un fichier unique est préférable — les mixins ajoutent de la complexité (MRO, fichiers multiples) sans bénéfice lisible. `CrowdSecAgent` (6 fonctions) et `PfSenseAgent` (3 fonctions propres + héritage OPNsense) restent intentionnellement en fichier unique.

### 6. Décorateur `@safety_snapshot`

Utilisé sur **toutes** les méthodes destructives OPNsense :

1. Appelle `/api/firewall/filter/savepoint` avant la modification.
2. Laisse la modification s'exécuter.
3. En cas d'échec, le rollback est disponible via la console OPNsense.

---

## Auth (`server.py`)

Header `X-API-Key` requis sur `POST /agent/execute` et `GET /capabilities`.

- Variable d'environnement : `AGENT_API_KEY`
- Non configurée → mode dev, avertissement au démarrage, accès libre
- Mauvaise clé → HTTP 401 `{"error": "UNAUTHORIZED"}`

---

## Route `/capabilities`

Endpoint de **découverte dynamique** des outils. Utilisé par le coordinateur au démarrage pour construire son registre de fonctions disponibles.

```json
{
  "server_version": "2.2",
  "agents": [
    {
      "name": "opnsense",
      "inference": "vllm|ollama|simulation",
      "function_count": 42,
      "functions": [ { "name": "...", "description": "...", "parameters": {}, "required": [], "aliases": [] } ]
    }
  ]
}
```

---

## Protocoles de sécurité critiques

### Correspondances dangereuses

Ne jamais permettre une correspondance floue entre intentions opposées.

- **Catégorie ADD** : `create`, `enable`, `add`, `block`, `start`, `new`
- **Catégorie DEL** : `remove`, `disable`, `delete`, `unblock`, `stop`, `kill`

Règle : si le LLM hallucine `remove_ip` mais que seule `add_ip` existe → **FAIL** obligatoire, pas d'exécution de l'opposé.

### Sanitisation des arguments

- Typer clairement tous les paramètres de méthode.
- Les positionnels sans défaut sont **obligatoires** — le guard valide avant tout appel.
- `**kwargs` tolère les arguments supplémentaires hallucination sans planter.

### Support bilingue FR/EN

Les prompts système et les données d'entraînement sont bilingues. Le moteur parse `Pensée:` comme marqueur de raisonnement (en plus de `<thought>` et `Reasoning:`). Maintenir ce support.

---

## Documentation des fonctions — Contrat avec `get_capabilities()`

`get_capabilities()` dans `agents/base.py` introspète les fonctions enregistrées et construit automatiquement les schémas OpenAI function-calling exposés au LLM coordinateur. **La documentation de chaque méthode agent EST son interface — toute lacune se traduit directement par des hallucinations du LLM.**

Deux mécanismes sont extraits automatiquement :

### 1. `Literal[...]` → champ `enum` dans le schéma

Tout paramètre annoté `Literal["a", "b", "c"]` génère `"enum": ["a", "b", "c"]` dans le schéma JSON. Le LLM voit les valeurs valides directement dans son contexte.

```python
# ✅ CORRECT — le LLM connaît les valeurs valides
async def _create_filter_rule(
    self,
    interface: Literal["wan", "lan", "opt1", "opt2"],
    action: Literal["block", "pass"] = "block",
) -> Dict:
    ...

# ❌ INCORRECT — enum absent du schéma, hallucinations probables
async def _create_filter_rule(
    self,
    interface: str,    # le LLM peut générer "WAN", "eth0", "internet"...
    action: str = "block",
) -> Dict:
    ...
```

**Règle : tout paramètre à valeurs discrètes DOIT être annoté `Literal[...]`.**

### 2. `:param name:` → champ `description` dans le schéma

`_parse_param_docs()` extrait les sections `:param name: texte` de la docstring et les injecte comme `"description"` dans le schéma du paramètre. Ces descriptions guident le LLM pour produire les bonnes valeurs.

```python
# ✅ CORRECT — description + exemples + anti-valeurs documentées
async def _ban_ip(
    self,
    ip: str,
    duration: str = "4h",
) -> Dict:
    """Bannit une adresse IP via CrowdSec LAPI.

    :param ip: Adresse IP à bannir (ex: "203.0.113.45").
    :param duration: Durée au format Go duration (ex: "4h", "24h", "168h").
        Valeurs courantes : "1h" (1 heure), "4h" (4 heures), "168h" (1 semaine).
    """

# ❌ INCORRECT — description absente du schéma, le LLM se débrouille seul
async def _ban_ip(self, ip: str, duration: str = "4h") -> Dict:
    """Bannit une IP."""
```

**Règle : chaque paramètre DOIT avoir une section `:param name:` dans la docstring.**

### Bonnes pratiques pour les descriptions `:param`

- Toujours inclure au moins un exemple concret : `(ex: "203.0.113.45")`
- Documenter les anti-valeurs si le LLM risque de les halluciner :
  `NE PAS utiliser 'allow', 'deny' ou 'drop' — uniquement 'block' ou 'pass'`
- Préciser le format attendu pour les types non-évidents :
  `format Go duration (ex: "4h", "24h", "168h")` ou `format RFC3339 (ex: "2026-01-01T00:00:00Z")`
- Documenter le comportement si omis : `Omis = toutes les décisions`

### Checklist avant commit d'une méthode agent

- [ ] Tous les paramètres à valeurs discrètes annotés `Literal[...]`
- [ ] Chaque paramètre a une section `:param name:` dans la docstring
- [ ] Exemples concrets inclus dans les descriptions
- [ ] Anti-valeurs documentées si risque d'hallucination
- [ ] `GET /capabilities` retourne les `enum` et `description` attendus après redémarrage

### Convention commits git

Les messages de commit **ne doivent pas** contenir de référence à l'agent ou à l'outil IA qui a produit le changement (pas de `Co-Authored-By`, pas de `Generated by`, pas de mention de Claude, GPT, Copilot, etc.). Le commit doit décrire le changement, pas son auteur.

---

## Gotchas de développement

### 1. Erreur "Double Model" vLLM

Si `NativeVLLMClient` est instancié deux fois sans `shutdown()`, erreur `Distributed state already initialized`. Toujours utiliser le singleton `NativeVLLMClient._instance`.

### Arrêt propre du coordinateur / tool-agent (SIGINT / CTRL+C)

**Problème** : vLLM v1 exécute son `EngineCore` dans un sous-processus (`EngineCore_DP0`). Si le processus principal reçoit SIGINT brut, le sous-processus l'obtient simultanément (même process group) et mourait avant le nettoyage, émettant :

```
[W] destroy_process_group() was not called before program exit (ProcessGroupNCCL.cpp)
```

**Fix appliqué (entrypoints `__main__`)** :

- Remplacer `uvicorn.run()` par `uvicorn.Server` + `install_signal_handlers = lambda: None`
- Installer un handler SIGINT/SIGTERM perso qui pose `server.should_exit = True`
- `timeout_graceful_shutdown=30` → uvicorn attend 30 s que le lifespan finisse
- Le lifespan appelle `vllm_client.shutdown()` → `del self.llm` → `LLM.__del__` → EngineCore reçoit un message IPC d'arrêt au lieu de SIGKILL

**Si lancé via CLI uvicorn (pas `__main__`)** : ajouter `--timeout-graceful-shutdown 30` à la commande.

**Démarrage séquentiel obligatoire** : deux instances vLLM sur le même GPU ne peuvent pas s'initialiser en parallèle. vLLM prend un snapshot de VRAM libre au démarrage et échoue avec `AssertionError: Initial free memory X GiB, current free memory Y GiB` si un autre processus modifie la VRAM pendant la phase torch.compile (~80 s).

```bash
# Étape 1 — attendre "✅ Agents initialized."
python server.py

# Étape 2 — seulement APRÈS que le tool-agent est stable
uvicorn coordinator.server:app --host 0.0.0.0 --port 3001 --timeout-graceful-shutdown 30
```

**Budget VRAM (RTX 4070 Ti 12 GB)** :

| Process | Modèle | `gpu_memory_utilization` | VRAM physique |
|---|---|---|---|
| tool-agent (`server.py`) | Qwen2.5-3B-Instruct 4-bit LoRA | `TOOL_AGENT_GPU_UTIL=0.45` | ~5.4 GB |
| coordinateur | Qwen2.5-3B-Instruct 8-bit | `COORDINATOR_GPU_UTIL=0.89` | ~3.3 GB |

**Total physique ~8.7 GB sur 12 GB.** Le paramètre `COORDINATOR_GPU_UTIL` doit paraître élevé (0.89) pour une raison précise :

> vLLM mesure la **VRAM totale** (tous les processus) lors du profiling KV-cache, pas uniquement son propre delta.
> `kv_cache = GPU_UTIL × total − peak_profiling`
> `peak_profiling = tool_agent(5.4) + model_weights(2.29) + overhead(1.13) = 8.82 GB`
> Avec `VLLM_MAX_MODEL_LEN=8192` : `COORDINATOR_GPU_UTIL=0.89` → KV=0.89×12−8.82=1.85 GB
> (0.90 échoue au startup : 0.90×12=10.8 > 10.75 GiB libres au démarrage)

**Règle générale** : mesurer `free_VRAM` empiriquement au démarrage du tool-agent (`nvidia-smi`), puis `GPU_UTIL ≤ free_VRAM / total_VRAM`.

Options alternatives :
- `COORDINATOR_GPU_UTIL=0.89` + `COORDINATOR_MODEL=Qwen/Qwen2.5-3B-Instruct` + `VLLM_MAX_MODEL_LEN=8192` ← ACTUEL
- `COORDINATOR_BACKEND=anthropic` (API externe, 0 GPU pour le coordinateur)

### 2. OPNsense 404 sur savepoint

Certaines versions OPNsense utilisent des endpoints de savepoint différents. `OPNsenseAPIClient` dispose de `suppress_log_404` dans `_request` pour gérer ces fallbacks silencieusement.

### 3. WSL / CUDA

Sous WSL, `pin_memory=False` est souvent nécessaire pour la stabilité. Géré automatiquement — surveiller les erreurs CUDA dans `server.log`.

### 5. HuggingFace XetHub / CAS : `HF_HUB_DISABLE_XET=1` requis

Certains modèles HuggingFace (dont `unsloth/Phi-3-mini-4k-instruct`) utilisent le backend de stockage XetHub/CAS.
Le téléchargement via `xet_get` échoue avec `ReqwestMiddleware Error: Request failed after 5 retries` sur
des réseaux restrictifs ou derrière un proxy.

**Fix** : exporter `HF_HUB_DISABLE_XET=1` avant tout script d'entraînement ou de téléchargement :

```bash
HF_HUB_DISABLE_XET=1 python scripts/train_opnsense_lora.py
```

Alternative : utiliser `microsoft/Phi-3-mini-4k-instruct` (poids identiques, stockage LFS standard, pas de xet).

### 6. Housekeeping — Repos externes clonés pour extraction de données

Lorsqu'un repo externe est cloné pour en extraire des schémas ou des données (ex: `opnsense-mcp-server`, `opnsense-typescript-client`), le clone est **temporaire**. Règle :

1. Cloner dans `/tmp/` uniquement (jamais dans `/srv/`)
2. Extraire le produit utile vers `data/schemas/` ou `data/sft/`
3. Supprimer le clone immédiatement après extraction (`rm -rf /tmp/<repo>`)

Seuls les artefacts finaux sont conservés et versionnés :
```
data/schemas/opnsense_mcp_full.json   ← schémas extraits (versionné)
data/sft/opnsense_mcp_train.jsonl     ← exemples SFT générés (versionné)
```
Ne jamais committer un repo cloné, des `node_modules/`, ou des binaires TypeScript compilés.

### 7. Dataset MCP — `content` dict au lieu de string

Certaines traces générées par `generate_opnsense_mcp_sft.py` produisent un message assistant avec `content` en dict (`{'type': 'erreur', 'message': '...'}`) au lieu d'une string. HuggingFace `datasets` lève une `ArrowInvalid` au chargement (changement de type de colonne).

**Fix** : `merge_opnsense_datasets.py` normalise systématiquement tout `content` non-string en JSON string lors du chargement. Ne pas retirer cette normalisation.

### 4. CrowdSec : stop tokens explicites

Le LoRA CrowdSec boucle sans stop tokens. `_infer_with_ollama` passe une liste explicite :
`["OBSERVATION:", "Checking", "</s>", "<|endoftext|>"]`
Ne pas supprimer ces tokens lors d'une mise à jour du LoRA.

### 8. Unsloth 2026.2.x — `KeyError: 'sanitize_logprob'`

Depuis unsloth 2026.2.1, `unsloth/models/rl.py:289` référence `RL_REPLACEMENTS["sanitize_logprob"]`
qui n'existe pas dans `unsloth_zoo/rl_replacements.py` de la même version (désynchronisation de packages).

**Fix** : mettre à jour `unsloth-zoo` seul (pas `unsloth`) :

```bash
pip install --upgrade unsloth-zoo
# unsloth_zoo 2026.2.1 → 2026.3.2
```

Après mise à jour, Unsloth redevient opérationnel avec les kernels triton. Si la mise à jour n'est pas possible, `_check_unsloth()` dans `lora_trainer.py` attrape `Exception` (pas seulement `ImportError`) et bascule sur HF standard.

### 10. Unsloth + `HF_HUB_OFFLINE=1` — model_name non résolu

Unsloth `FastLanguageModel.from_pretrained("Qwen/Qwen2.5-3B-Instruct")` avec `HF_HUB_OFFLINE=1` lève :

```
RuntimeError: Unsloth: No config file found - are you sure the `model_name` is correct?
```

Le modèle est pourtant en cache HF. La cause : `unsloth_zoo/hf_utils.py::get_transformers_model_type()` ne résout pas le chemin de snapshot correctement en mode offline.

**Fix** dans les scripts d'entraînement Qwen25 : résoudre le chemin local **avant** de passer au trainer, via `snapshot_download(local_files_only=True)` :

```python
def _local_model_path(model_id: str) -> str:
    try:
        from huggingface_hub import snapshot_download
        return snapshot_download(model_id, local_files_only=True)
    except Exception:
        return model_id  # fallback réseau

trainer = LoRATrainer(base_model=_local_model_path("Qwen/Qwen2.5-3B-Instruct"), ...)
```

Ne pas mettre `HF_HUB_OFFLINE=1` dans les scripts Qwen25 — garder seulement `TRANSFORMERS_OFFLINE=1` (qui n'interfère pas avec `huggingface_hub.snapshot_download`).

### 11. Mismatch format entraînement / inférence — cause de résultats catastrophiques

**Symptôme** : LoRA fine-tuné sur un nouveau modèle de base (ex: Qwen2.5-3B-Instruct à la place de Phi-3.5-mini) — verification rate proche de 0 %, toutes les fonctions mal prédites.

**Cause** : `format_single_example_to_text()` dans `lora_trainer.py` était hardcodé pour le format de prompt Phi-3 (`<|system|>`, `<|user|>`, `<|assistant|>`, `<|endoftext|>`). Le script de vérification utilise `tokenizer.apply_chat_template()` qui produit le format natif du modèle (pour Qwen2.5 : `<|im_start|>system`, `<|im_end|>`, etc.). Le LoRA apprend un format, et voit un format différent à l'inférence.

**Fix** (2026-03-15) : `format_single_example_to_text()` utilise désormais `self.tokenizer.apply_chat_template()` — le format d'entraînement est automatiquement calqué sur le chat template du modèle de base chargé. Les `tool_calls` (format custom) sont convertis en JSON string dans le `content` de l'assistant avant appel au template.

**Règle** : toujours vérifier la cohérence format entraînement ↔ inférence lors d'un changement de modèle de base. Un premier test rapide : afficher un exemple formaté avant le `trainer.train()` et le comparer au prompt produit par `build_prompt()` dans le script de vérification.

### 9. Arrow schema inference — JSONL avec `tool_calls.arguments` hétérogènes

`load_dataset("json", data_files=...)` infère le schéma Arrow à partir des N premiers exemples.
Les datasets OPNsense contiennent des `tool_calls.arguments` avec des structures différentes selon la fonction
(`firewall_rule` ≠ `nat_rule` ≠ `alias`) → Arrow lève `TypeError: Couldn't cast array of type struct<...>`
lors du chargement du batch suivant.

**Fix** : dans `trainers/lora_trainer.py`, `_load_jsonl()` sérialise `messages` en JSON string avant création
du `HFDataset` → schéma plat `{"_msgs": string}`, homogène, pas d'inférence de struct :

```python
def _load_jsonl(path):
    rows = []
    with open(path) as f:
        for line in f:
            ex = json.loads(line.strip())
            rows.append({"_msgs": json.dumps(ex["messages"])})
    return HFDataset.from_list(rows)
```

`process_sample()` désérialise avec `json.loads(example["_msgs"])`.
Ne jamais revenir à `load_dataset("json", ...)` pour les datasets OPNsense.

---

## Inférence Multi-LoRA (Phase 4)

### Attributs de classe `ToolAgent`

Chaque agent-outil hérite de `ToolAgent` (`agents/base.py`) et déclare trois attributs de classe :

| Attribut | Rôle | Valeur actuelle |
|---|---|---|
| `agent_role` | Description courte (fallback si `system_prompt` vide) | `"OPNsense firewall agent"` etc. |
| `system_prompt` | Prompt système exact à l'inférence — **doit correspondre au dataset d'entraînement** | CAP v1 FR spécifique à chaque agent |
| `chat_format` | Template de prompt : `"qwen"` ou `"phi3"` | `"qwen"` depuis migration Qwen2.5 |

`_infer_with_vllm()` dans `base.py` construit le prompt formaté en utilisant `self.system_prompt` + `self.chat_format`. Changer de modèle de base → mettre à jour les deux attributs.

### Découverte des adapters — `_discover_lora_adapters()` (`server.py`)

Scanne `loras/`, filtre par `base_model_name_or_path` dans `adapter_config.json` et **normalise le nom de l'adapter** pour le faire correspondre à `tool_name` de l'agent :

```
opnsense_lora/         → agent_name "opnsense"
opnsense_qwen25_lora/  → agent_name "opnsense"  ← suffixe _qwen25 retiré
wireguard_qwen25_lora/ → agent_name "wireguard"
```

Suffixes normalisés : `_qwen25`, `_qwen3`, `_phi3`, `_phi35`.

Configuration `.env` :
```bash
TOOL_AGENT_BASE_MODEL=Qwen/Qwen2.5-3B-Instruct   # modèle de base commun à tous les adapters
TOOL_AGENT_GPU_UTIL=0.45                           # GPU utilization pour vLLM tool-agent
```

Lors du démarrage de `server.py`, seuls les adapters dont `base_model_name_or_path == TOOL_AGENT_BASE_MODEL` sont chargés dans le moteur vLLM. Les autres agents fonctionnent en fallback Ollama / simulation.

---

## Catalogue des agents

| Agent | `tool_name` | Domaine | Nb fonctions |
| --- | --- | --- | --- |
| `opnsense` | `opnsense` | Firewall / NAT / VPN OPNsense | 102 |
| `wireguard` | `wireguard` | Tunnels & pairs WireGuard | 11 |
| `crowdsec` | `crowdsec` | IDPS — bans, décisions, alertes | 15 |
| `anony` | `anony` | Anonymisation de logs & documents | 5 |

### Agent `anony` — Anonymisation (`agents/anony/`)

Orchestre `anonyfiles_core` (fork `/srv/anonyfiles`) pour anonymiser logs et documents.
Utilise **AnonyNER** (modèle spaCy custom) pour la détection d'entités cybersécurité.

**Fonctions exposées :**
- `anonymize_text(text)` — anonymise un texte, retourne `{anonymized_text, mapping}`
- `anonymize_batch(texts, reset_session)` — batch cohérent (même entité → même token)
- `deanonymize_text(anonymized_text)` — réversibilité via mapping de session
- `get_session_mapping()` — mapping courant `{original: token}`
- `reset_session()` — repart d'une session vierge

**Modèle NER — priorité de résolution :**
1. Package installé `fr_anonyner` → `pip install dist/fr_anonyner-*.tar.gz`
2. Répertoire local `models/anonyner_model/model-best` → après `python scripts/train_anonyner.py`
3. Fallback `fr_core_news_md` → entités cyber non détectées (warning au démarrage)

**Régénérer et installer le package `fr_anonyner` :**
```bash
# Depuis /srv/cyber-agent-engine
python -m spacy package \
  models/anonyner_model/model-best dist/ \
  --name anonyner --version 2.0.0 --build sdist --force
pip install dist/fr_anonyner-2.0.0/dist/fr_anonyner-2.0.0.tar.gz
```

**Labels détectés par AnonyNER v2 (F1=88.6%) :**
`IP_ADDRESS`, `IP_SUBNET`, `HOSTNAME`, `DOMAIN`, `CVE`, `MAC_ADDRESS`,
`SERVICE_ACCOUNT`, `FIREWALL_RULE`, `INTERFACE`, `PORT_NUMBER`, `VPN_USER`, `PROTOCOL`

**Règles regex complémentaires :** `agents/anony/config/custom_rules_security.json`
(IP RFC1918, CVE, FQDN, MAC, tokens hex — détection avant le passage NER)

---

## Ajouter une capacité

1. **Client bas-niveau** : `factory/clients/<outil>_client.py` — méthode `await self._request(...)`
2. **Méthode agent** : ajouter dans le mixin approprié (ou créer un nouveau mixin), décorer `@safety_snapshot` si opération d'écriture
3. **Documentation** : appliquer la checklist de la section ["Documentation des fonctions"](#documentation-des-fonctions--contrat-avec-get_capabilities) :
   - Annoter `Literal[...]` sur tous les paramètres à valeurs discrètes
   - Ajouter `:param name:` dans la docstring pour chaque paramètre
4. **Enregistrement** : ajouter dans `_register_functions()` du mixin concerné
5. **Classifier** : vérifier / enrichir les mots-clés dans `agents/classifier.py`
6. **Init serveur** : si nouvel agent, l'instancier dans le bloc lifespan de `server.py`
7. **Validation** :
   - Tester avec une commande qui *omet* un argument → doit retourner `error_code: MISSING_ARG`
   - Tester l'intent inverse (ex. "supprimer" vs "créer") → doit refuser, pas exécuter l'opposé
   - Vérifier que `GET /capabilities` retourne la nouvelle fonction avec ses `enum` et `description`

---

---

## Agent Coordinateur (`coordinator/`)

Service séparé (port **3001**) qui reçoit des demandes haut niveau, les décompose en sous-tâches et délègue au tool-agent-server (port 3000).

### Architecture interne

```text
coordinator/
├── server.py               FastAPI port 3001 + checkpoint watchdog
├── pilot.py                PilotAgent — plan / execute / synthesize / judge
├── state.py                Task, PlanState (checkpoint_at), CheckpointStore
├── judge.py                CAPValidator — validation schema avant exécution
├── clients/
│   └── tool_agent_client.py   HTTP vers port 3000 (retry + cache capabilities)
├── llm/
│   └── coordinator_llm.py     Wrapper Qwen2.5-3B vLLM ou Ollama
└── prompts/
    ├── system.yaml         Contexte réseau (opnsense/wireguard/crowdsec)
    ├── planning.yaml       Décomposition en tâches JSON
    ├── routing.yaml        Sélection du prochain agent
    └── synthesis.yaml      Rapport Markdown final
```

#### `coordinator/judge.py` — CAPValidator

Validation déterministe des CAP (Coordinator-Agent Packets) **avant** envoi au tool-agent. Pas de LLM — logique de schéma pure.

```python
@dataclass
class JudgeVerdict:
    passed: bool
    reason: str
    missing_args: list[str]   # args obligatoires absents
    invalid_enums: dict        # param → valeur_fournie vs valeurs_valides
```

`CAPValidator.validate(cap, agent_name)` retourne un `JudgeVerdict`. Vérifie :
1. La directive existe dans le registre de capacités de l'agent
2. Les arguments obligatoires sont tous présents
3. Les valeurs des paramètres `Literal[...]` sont dans l'enum déclaré

`CAPValidator.update(capabilities)` est appelé dans `pilot.py` à chaque `_fetch_capabilities()` pour maintenir l'index à jour.

Dégradation gracieuse : si l'index est vide (capabilities pas encore chargées), `passed=True` pour ne pas bloquer le démarrage.

#### `pilot.py` — améliorations (2026-03-15)

- **`_judge_cap(cap, agent_name)`** : appelle `CAPValidator.validate()` avant chaque `execute_cap()`. Si verdict `passed=False`, logue l'erreur et retourne un `ToolResult` d'échec sans appel réseau.
- **`_auto_list` — retry x3 avec backoff** : si `list_capabilities()` échoue, retry à 2 s, 4 s, puis échec définitif. Évite les panics au démarrage si le tool-agent tarde.
- **`_summarize_capabilities`** : inclut désormais `fn_desc` (description de la fonction) dans les lignes de mutation — le LLM coordinateur voit le contexte de chaque action destructive.
- **`state.checkpoint_at`** : timestamp `float` posé lors de chaque transition vers `CHECKPOINT_WAIT`. Utilisé par le watchdog.

#### `server.py` — checkpoint watchdog (2026-03-15)

`_checkpoint_watchdog()` : tâche asyncio démarrée dans le lifespan. Toutes les 30 s, parcourt les plans en `CHECKPOINT_WAIT` et auto-rejette ceux dont `checkpoint_at` dépasse `CHECKPOINT_TIMEOUT` (défaut : 300 s, configurable via `CHECKPOINT_TIMEOUT` env var). Évite les plans orphelins qui bloquent des ressources indéfiniment.

### State machine d'un plan

```text
PLANNING → EXECUTING → SYNTHESIZING → DONE
                ↓
         CHECKPOINT_WAIT ──approve──→ EXECUTING
                ↓
              reject
                ↓
            ABORTED
```

### API du coordinateur

| Méthode | Route | Description |
| --- | --- | --- |
| `POST` | `/coordinator/execute` | Lance un plan (body: `{"query": "..."}`) |
| `GET` | `/coordinator/status/{run_id}` | État complet d'un plan |
| `GET` | `/coordinator/checkpoint/{run_id}` | Tâches en attente d'approbation |
| `POST` | `/coordinator/checkpoint/{run_id}/approve` | Approuver et reprendre |
| `POST` | `/coordinator/checkpoint/{run_id}/reject` | Avorter le plan |
| `GET` | `/coordinator/capabilities` | Proxy vers `/capabilities` port 3000 |

### Checkpoints humains

Les actions détectées comme destructives (contenant `delete`, `remove`, `ban`, `block`, `disable`, `supprim`, `efface`, `désactiv`) sont marquées `requires_approval=True` par le LLM.
Le plan s'interrompt avec `status: checkpoint_wait` — l'opérateur consulte les tâches en attente et approuve ou rejette avant la reprise.

### Auth du coordinateur

Header `X-API-Key` requis sur toutes les routes sauf `/coordinator/health`.

- Variable d'environnement : `COORDINATOR_API_KEY`
- Non configurée → mode dev, avertissement au démarrage, accès libre
- Mauvaise clé → HTTP 401 `{"error": "UNAUTHORIZED"}`

Toute nouvelle route du coordinateur **doit** inclure `dependencies=[Depends(verify_api_key)]` :

```python
@app.post("/coordinator/nouvelle_route", dependencies=[Depends(verify_api_key)])
async def nouvelle_route(...):
    ...
```

### Variables d'environnement

```bash
TOOL_AGENT_URL=http://localhost:3000       # URL du tool-agent-server
TOOL_AGENT_KEY=                            # même valeur que AGENT_API_KEY
COORDINATOR_API_KEY=changeme-strong-key    # clé pour protéger le coordinateur
COORDINATOR_BACKEND=vllm                   # "vllm" ou "ollama"
COORDINATOR_MODEL=Qwen/Qwen2.5-3B-Instruct
COORDINATOR_GPU_UTIL=0.89                  # voir budget VRAM ci-dessus
VLLM_MAX_MODEL_LEN=8192                    # taille contexte coordinateur
COORDINATOR_OLLAMA_MODEL=qwen2.5:3b        # si BACKEND=ollama
CHECKPOINT_TIMEOUT=300                     # secondes avant auto-rejet checkpoint (défaut 300)
```

### Démarrage

```bash
# Tool agents (port 3000)
python server.py

# Coordinateur (port 3001)
python -m coordinator.server
# ou
uvicorn coordinator.server:app --host 0.0.0.0 --port 3001
```

---

*Document version : 3.0 — Phase 4 : inférence Multi-LoRA Qwen2.5 (chat_format, system_prompt, _discover_lora_adapters normalization)*
*Cible : Agents coordinateurs IA & développeurs avancés.*
