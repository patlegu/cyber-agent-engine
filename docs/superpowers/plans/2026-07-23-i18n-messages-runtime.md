# i18n des messages runtime (D3d) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normaliser tous les messages runtime destinés à l'opérateur en anglais canonique (inline, sans infra i18n) sur la surface first-party, avec un garde-fou AST anti-régression.

**Architecture:** Sweep de traduction en dur, couche par couche (core+coordinator+server → clients → agents hors opnsense → agents/opnsense), puis un test AST permanent qui échoue si un message opérateur accentué FR réapparaît. Les cibles exactes (fichier:ligne + chaîne FR) sont dans l'inventaire committé `docs/superpowers/plans/2026-07-23-i18n-inventory.md`.

**Tech Stack:** Python 3.11, `ast` (stdlib) pour le garde-fou et la vérification par couche, pytest. Venv : `.venv/bin/`.

## Global Constraints

- **Périmètre = messages opérateur** : littéraux chaîne passés à `raise <Exc>(…)` (args + kwargs, ex. `detail=`), aux méthodes de log `debug/info/warning/warn/error/critical/exception/log` (args + kwargs), à `print(…)`, **et** aux champs de réponse opérateur `reason=` / `error=` (objets `Failed`/`Denied`/`AgentExecuteResponse`). Cible mesurée : **229** (T1 17, T2 18, T3 74, T4 120).
- **Restent en français (NE PAS traduire)** : docstrings (y c. docstrings d'attributs PEP 257), commentaires, prompts LLM (`coordinator/proposer.py`), descriptions de fonctions/outils LLM (dicts `"description": …`), vocabulaire de matching du classifier (`agents/classifier.py`), regex parsant la sortie ReAct française (`agents/base.py` `'Pensée\s*:'`, etc.), documentation utilisateur (bilingue, inchangée).
- **Traduire le message ENTIER** : l'accent n'est qu'un localisateur. Dans une même chaîne/f-string, traduire aussi les fragments français **sans accent** (ex. `f"approbation {id} en état {s}"` → `f"approval {id} in state {s}"` : `approbation ` **et** ` en état ` passent en anglais).
- **Préserver** : interpolations f-string (`{…}`), spécificateurs `%s`/`%(name)s`/`%d`, emojis (`✓ ✅ ❌ ⚠️ ℹ️`), et préfixes-tags structurants (`[OPNsense]`, `[Stormshield]`).
- **Glossaire (cohérence obligatoire sur les 229)** : règle→rule, alias→alias, clé→key, équipement→device, aucun→no, absent→missing, invalide→invalid, réponse→response, requête→request, initialisé→initialized, activé→enabled, désactivé→disabled, introuvable→not found, échoué/échec→failed, créé→created, supprimé→removed, ajouté→added, retiré→removed, modifié→modified, appliqué→applied, annulé→cancelled (rollback→rolled back), démarré→started, arrêté→stopped, généré→generated, chargé→loaded, téléchargement→download, sauvegarde→backup, effectué→performed, vidé→flushed, connexion refusée→connection refused, expiré→expired, rejeté→rejected, malformé→malformed, non sérialisé→unserialized.
- **Non-régression** : les 201 tests A→D3b restent verts après chaque tâche. Un seul test asserte du texte runtime FR (`tests/coordinator/test_proposer.py:42 == "terminé"`) mais `"terminé"` est une **donnée de fixture** (fausse sortie LLM), pas un littéral de code → non impacté. Si une traduction casse un test qui asserte l'ancien texte, mettre à jour ce test dans la même tâche.
- **CQI > 9**, test-first pour le garde-fou. Commits `type(scope): sujet` minuscules, sans emoji, sans `Co-Authored-By` ni mention d'IA.

---

## Vérification par couche (utilisée par T1→T4)

Chaque tâche de sweep se vérifie en scannant SES fichiers : zéro message opérateur accentué restant. Commande générique (adapter la liste de chemins à la tâche) :

```bash
.venv/bin/python - <<'PY'
import ast, sys
from pathlib import Path
ROOT = Path(".")
PATHS = sys.argv[1:]  # fichiers de la couche
ACC = set("éèàçêîôûïœÉÈÀÇÊÎÔÛÏŒëüö")
LOG = {"debug","info","warning","warn","error","critical","exception","log"}
def cn(f): return f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
def accs(n): return [x.value for x in ast.walk(n) if isinstance(x, ast.Constant) and isinstance(x.value, str) and any(c in ACC for c in x.value)]
bad = []
for p in PATHS:
    t = ast.parse(Path(p).read_text(encoding="utf-8"))
    for node in ast.walk(t):
        s = []
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            for a in node.exc.args: s += accs(a)
            for kw in node.exc.keywords: s += accs(kw.value)
        elif isinstance(node, ast.Call):
            nm = cn(node.func)
            if nm in LOG:
                for a in node.args: s += accs(a)
                for kw in node.keywords: s += accs(kw.value)
            elif nm == "print":
                for a in node.args: s += accs(a)
            for kw in node.keywords:
                if kw.arg in ("reason", "error"): s += accs(kw.value)
        for x in s: bad.append(f"{p}:{node.lineno} {x[:60]!r}")
print("RESTANTS:", len(bad))
for b in bad: print(" ", b)
PY
<chemins des fichiers de la couche>
```

Attendu après traduction : `RESTANTS: 0`.

---

### Task 1 : Sweep core/ + coordinator/ + server.py

**Files (modify) :** `coordinator/app.py`, `coordinator/assembly.py`, `coordinator/loop.py`, `coordinator/session.py`, `core/auth/api_key.py`, `core/execution/authorization.py`, `core/policy/loading.py`, `server.py`
**Test :** aucun test nouveau (le garde-fou permanent est T5) ; non-régression suite complète.
**Inventaire :** section `## T1` de `docs/superpowers/plans/2026-07-23-i18n-inventory.md`.

**Interfaces :** aucune signature modifiée — uniquement le contenu de littéraux chaîne.

- [ ] **Step 1 : Traduire les 17 cibles T1 (traductions exactes ci-dessous)**

Lis chaque ligne pour le contexte f-string, puis applique :

| Fichier:ligne | FR (fragment) | EN |
|---|---|---|
| `coordinator/app.py:48` (raise) | `variante LoopResult non sérialisée : ` | `unserialized LoopResult variant: ` |
| `coordinator/assembly.py:66` (raise) | `f"…'{name}' exposé par plusieurs serveurs (routage ambigu)"` | `…'{name}' exposed by multiple servers (ambiguous routing)` |
| `coordinator/assembly.py:71` (raise) | `aucun agent découvert sur les serveurs d'agents` | `no agent discovered on the agent servers` |
| `coordinator/loop.py:102` (reason=) | `session inconnue ou expirée` | `unknown or expired session` |
| `coordinator/loop.py:114` (reason=) | `f"approbation en état {…}"` | `approval in state {…}` |
| `coordinator/loop.py:142` (reason=) | `rejeté par l'opérateur` | `rejected by the operator` |
| `coordinator/session.py:102` (raise) | `f"{var} absent : le coordinateur refuse de démarrer"` | `{var} missing: the coordinator refuses to start` |
| `core/auth/api_key.py:26` (raise) | `f"{var} absent ou vide : le coordinateur refuse de démarrer sans authentification"` | `{var} missing or empty: the coordinator refuses to start without authentication` |
| `core/auth/api_key.py:43` (raise, detail=) | `clé API invalide ou absente` | `invalid or missing API key` |
| `core/execution/authorization.py:29` (raise) | `Authorized ne peut être construit que par grant()/grant_approved()` | `Authorized can only be built by grant()/grant_approved()` |
| `core/execution/authorization.py:46` (raise) | `f"approbation {id} en état {state}"` | `approval {id} in state {state}` |
| `core/policy/loading.py:31` (raise) | `f"règle #{i} malformée : {exc}"` | `rule #{i} malformed: {exc}` |
| `core/policy/loading.py:34` (raise) | `f"règle #{i} '…' ne couvre aucune capacité connue"` | `rule #{i} '…' covers no known capability` |
| `server.py:138` (log) | `  ⚠️  Adapter '%s' ignoré — base model incompatible (adapter: %s, attendu: %s). Re-entraîner…` | `  ⚠️  Adapter '%s' skipped — incompatible base model (adapter: %s, expected: %s). Retrain…` |
| `server.py:342` (error=) | `Aucun agent n'a pu interpréter cette commande.` | `No agent could interpret this command.` |

(Les deux fragments `règle #` de `loading.py` L31/L34 sont les préfixes des f-strings ci-dessus — un seul par ligne.)

- [ ] **Step 2 : Vérifier la couche — 0 restant**

Run (bloc de vérification par couche ci-dessus) avec :
`coordinator/app.py coordinator/assembly.py coordinator/loop.py coordinator/session.py core/auth/api_key.py core/execution/authorization.py core/policy/loading.py server.py`
Expected : `RESTANTS: 0`.

- [ ] **Step 3 : Non-régression**

Run: `.venv/bin/pytest -q`
Expected : 201 passed (mettre à jour tout test cassé qui assertait l'ancien texte FR, puis re-run).

- [ ] **Step 4 : Commit**

```bash
git add coordinator/app.py coordinator/assembly.py coordinator/loop.py coordinator/session.py core/auth/api_key.py core/execution/authorization.py core/policy/loading.py server.py
git commit -m "i18n: messages operateur en anglais (core, coordinator, server)"
```

---

### Task 2 : Sweep clients/

**Files (modify) :** `clients/opnsense_api_client.py`, `clients/pfsense_api_client.py`, `clients/wireguard_linux_client.py`
**Inventaire :** section `## T2`.

**Interfaces :** aucune signature modifiée.

- [ ] **Step 1 : Traduire les 18 cibles T2 (traductions exactes)**

| Fichier:ligne | FR | EN |
|---|---|---|
| `opnsense_api_client.py:70` | `OPNsense API Client initialisé: ` | `OPNsense API client initialized: ` |
| `opnsense_api_client.py:650` | `Erreur téléchargement backup: ` | `Backup download error: ` |
| `pfsense_api_client.py:55` | `Client API pfSense initialisé (version: ` | `pfSense API client initialized (version: ` |
| `pfsense_api_client.py:114` | `Erreur requête ` | `Request error ` |
| `pfsense_api_client.py:259` | `Erreur récupération version: ` | `Version retrieval error: ` |
| `wireguard_linux_client.py:35` | `Client WireGuard Linux initialisé (config: ` | `WireGuard Linux client initialized (config: ` |
| `wireguard_linux_client.py:41` | `Exécution: ` | `Executing: ` |
| `wireguard_linux_client.py:56` (raise) | `f"Commande échouée ({…})"` | `Command failed ({…})` |
| `wireguard_linux_client.py:91` | `Paire de clés WireGuard générée` | `WireGuard key pair generated` |
| `wireguard_linux_client.py:106` | `PSK WireGuard générée` | `WireGuard PSK generated` |
| `wireguard_linux_client.py:156` | `f"…{…} créée ({…})"` | `…{…} created ({…})` |
| `wireguard_linux_client.py:170` | `f"…{…} démarrée"` | `…{…} started` |
| `wireguard_linux_client.py:173` | `Erreur démarrage ` | `Startup error ` |
| `wireguard_linux_client.py:180` | `f"…{…} arrêtée"` | `…{…} stopped` |
| `wireguard_linux_client.py:183` | `Erreur arrêt ` | `Stop error ` |
| `wireguard_linux_client.py:198` | `f"…{…} supprimée"` | `…{…} removed` |
| `wireguard_linux_client.py:235` | `Peer ajouté à ` | `Peer added to ` |
| `wireguard_linux_client.py:242` | `Peer supprimé de ` | `Peer removed from ` |

- [ ] **Step 2 : Vérifier la couche — 0 restant**

Run le bloc de vérification avec : `clients/opnsense_api_client.py clients/pfsense_api_client.py clients/wireguard_linux_client.py`
Expected : `RESTANTS: 0`.

- [ ] **Step 3 : Non-régression**

Run: `.venv/bin/pytest -q` → 201 passed.

- [ ] **Step 4 : Commit**

```bash
git add clients/opnsense_api_client.py clients/pfsense_api_client.py clients/wireguard_linux_client.py
git commit -m "i18n: messages operateur en anglais (clients reseau)"
```

---

### Task 3 : Sweep agents/ (hors opnsense)

**Files (modify) :** `agents/__init__.py`, `agents/anony/agent.py`, `agents/base.py`, `agents/coercion.py`, `agents/crowdsec_agent.py`, `agents/manifest.py`, `agents/ner_extractor.py`, `agents/pfsense_agent.py`, `agents/router_agent.py`, `agents/stormshield_agent.py`, `agents/tool_agents.py`, `agents/wireguard_agent.py`
**Inventaire :** section `## T3` (74 cibles, liste exhaustive fichier:ligne).

**Interfaces :** aucune signature modifiée.

- [ ] **Step 1 : Traduire les 74 cibles T3 depuis l'inventaire**

Pour CHAQUE ligne de la section `## T3` de l'inventaire : ouvrir le fichier à la ligne indiquée, traduire le message (entier, fragments non accentués compris) selon le glossaire, en **préservant** `%s`/`%d`, interpolations, emojis et tags. Exemples représentatifs des patterns rencontrés :

| FR | EN |
|---|---|
| `NERExtractor désactivé — AnonyNER introuvable` | `NERExtractor disabled — AnonyNER not found` |
| `NERExtractor initialisé (modèle : %s)` | `NERExtractor initialized (model: %s)` |
| `custom_rules chargées depuis %s (%d règles)` | `custom_rules loaded from %s (%d rules)` |
| `NER gap : '%s' (%s) détecté mais non anonymisé par le moteur` | `NER gap: '%s' (%s) detected but not anonymized by the engine` |
| `⚠️ Modèle LoRA non trouvé au chemin spécifié: ` | `⚠️ LoRA model not found at the specified path: ` |
| `✅ Inférence déportée active via Ollama` | `✅ Remote inference active via Ollama` |
| `ℹ️ Agent initialisé en mode 'Tools-Only' (pas de modèle LoRA local)` | `ℹ️ Agent initialized in 'Tools-Only' mode (no local LoRA model)` |
| `❌ Erreur lors du chargement du modèle LoRA: ` | `❌ Error loading the LoRA model: ` |
| `Aucun backend d'inférence configuré (AGENT_INFER_BASE_URL/ollama/[gpu]). …` | `No inference backend configured (AGENT_INFER_BASE_URL/ollama/[gpu]). …` |
| `. Types supportés: ` (raise) | `. Supported types: ` |
| `Session réinitialisée` | `Session reset` |
| `Erreur lors de l'exécution: ` | `Execution error: ` |

**Ne PAS toucher** dans ces fichiers : les regex ReAct de `agents/base.py` (`'Pensée\s*:'`, `'Action\s*:'`, `'Paramètre'` s'il sert au parsing), les dicts `"description"` d'outils, les docstrings. Si un doute : c'est un message de log/raise/`error=`/`reason=` → traduire ; sinon (donnée de matching, description LLM, docstring) → laisser.

- [ ] **Step 2 : Vérifier la couche — 0 restant**

Run le bloc de vérification avec la liste des 12 fichiers T3 ci-dessus.
Expected : `RESTANTS: 0`. (Si un restant est une regex/description/docstring légitime, il ne serait PAS remonté car le scan ne lit que raise/log/print/`reason=`/`error=` — donc 0 signifie bien tous les messages traités.)

- [ ] **Step 3 : Non-régression**

Run: `.venv/bin/pytest -q` → 201 passed.

- [ ] **Step 4 : Commit**

```bash
git add agents/__init__.py agents/anony/agent.py agents/base.py agents/coercion.py agents/crowdsec_agent.py agents/manifest.py agents/ner_extractor.py agents/pfsense_agent.py agents/router_agent.py agents/stormshield_agent.py agents/tool_agents.py agents/wireguard_agent.py
git commit -m "i18n: messages operateur en anglais (agents hors opnsense)"
```

---

### Task 4 : Sweep agents/opnsense/*

**Files (modify) :** `agents/opnsense/_aliases.py`, `_base.py`, `_config.py`, `_diagnostics.py`, `_extended.py`, `_filters.py`, `_ids.py`, `_legacy.py`, `_nat.py`, `_routing.py`, `_traffic.py`
**Inventaire :** section `## T4` (120 cibles, liste exhaustive fichier:ligne).

**Interfaces :** aucune signature modifiée.

- [ ] **Step 1 : Traduire les 120 cibles T4 depuis l'inventaire**

Même méthode que T3. Ces messages sont très réguliers (logs d'opérations OPNsense avec préfixe `[OPNsense]`, verbe d'action, et fragments f-string d'état). Préserver le tag `[OPNsense]`, les interpolations et emojis. Exemples représentatifs :

| FR | EN |
|---|---|
| `[OPNsense] Création alias: ` | `[OPNsense] Creating alias: ` |
| `f"…{…} créé et appliqué"` | `…{…} created and applied` |
| `Erreur création alias: ` | `Alias creation error: ` |
| `f"…{…} supprimé"` | `…{…} removed` |
| `f"…{…} modifié"` | `…{…} modified` |
| `f"…{…} effectué"` | `…{…} performed` |
| `f"…{…} vidé"` | `…{…} flushed` |
| `✓ Client API OPNsense initialisé` | `✓ OPNsense API client initialized` |
| `OPNsense: Initialisé sans API (mode locale/simulation)` | `OPNsense: initialized without API (local/simulation mode)` |
| `✓ Changements appliqués avec succès` | `✓ Changes applied successfully` |
| `✓ Rollback annulé, changements confirmés` | `✓ Rollback cancelled, changes confirmed` |
| `[OPNsense] Création savepoint` | `[OPNsense] Creating savepoint` |
| `✓ Savepoint créé: ` | `✓ Savepoint created: ` |
| `[OPNsense] Téléchargement backup configuration` | `[OPNsense] Downloading configuration backup` |

- [ ] **Step 2 : Vérifier la couche — 0 restant**

Run le bloc de vérification avec les 11 fichiers T4.
Expected : `RESTANTS: 0`.

- [ ] **Step 3 : Non-régression**

Run: `.venv/bin/pytest -q` → 201 passed.

- [ ] **Step 4 : Commit**

```bash
git add agents/opnsense/_aliases.py agents/opnsense/_base.py agents/opnsense/_config.py agents/opnsense/_diagnostics.py agents/opnsense/_extended.py agents/opnsense/_filters.py agents/opnsense/_ids.py agents/opnsense/_legacy.py agents/opnsense/_nat.py agents/opnsense/_routing.py agents/opnsense/_traffic.py
git commit -m "i18n: messages operateur en anglais (agents opnsense)"
```

---

### Task 5 : Garde-fou AST permanent

**Files :**
- Create: `tests/test_runtime_messages_english.py`

**Interfaces :**
- Consumes : la surface nettoyée par T1→T4.
- Produces : test permanent `test_no_french_operator_messages` (non-régression).

- [ ] **Step 1 : Écrire le garde-fou (doit être VERT d'emblée, tous les sweeps faits)**

```python
# tests/test_runtime_messages_english.py
"""Garde-fou : aucun message opérateur runtime en français accentué.

Scanne (AST) les littéraux chaîne passés à `raise`, aux méthodes de logging
(debug/info/warning/warn/error/critical/exception/log), à `print`, et aux champs
de réponse opérateur `reason=`/`error=`, sur la surface first-party ; échoue si un
caractère accentué français y apparaît. Par construction, docstrings, prompts LLM,
descriptions d'outils et vocab classifier ne sont jamais inspectés (ce ne sont pas
ces appels).

Limite connue : le français SANS accent (« timeout serveur ») n'est pas détecté ;
le sweep initial en assure la complétude, ce test garde la régression du cas
courant (accentué)."""
import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DIRS = ("core", "coordinator", "agents", "clients")
_ROOT_FILES = ("server.py",)
_ACCENTS = set("éèàçêîôûïœÉÈÀÇÊÎÔÛÏŒëüö")
_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log"}
_RESPONSE_FIELDS = {"reason", "error"}


def _sources():
    files = []
    for d in _DIRS:
        files.extend((_ROOT / d).rglob("*.py"))
    files.extend(_ROOT / f for f in _ROOT_FILES)
    return files


def _call_name(func):
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _accented(node):
    return [
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and any(c in _ACCENTS for c in n.value)
    ]


def _offenders(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        strs = []
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            for a in node.exc.args:
                strs += _accented(a)
            for kw in node.exc.keywords:
                strs += _accented(kw.value)
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in _LOG_METHODS:
                for a in node.args:
                    strs += _accented(a)
                for kw in node.keywords:
                    strs += _accented(kw.value)
            elif name == "print":
                for a in node.args:
                    strs += _accented(a)
            for kw in node.keywords:
                if kw.arg in _RESPONSE_FIELDS:
                    strs += _accented(kw.value)
        for s in strs:
            found.append(f"{path.relative_to(_ROOT)}:{node.lineno}  {s[:60]!r}")
    return found


def test_no_french_operator_messages():
    offenders = []
    for path in _sources():
        offenders.extend(_offenders(path))
    assert not offenders, "messages opérateur FR accentués:\n" + "\n".join(offenders)
```

- [ ] **Step 2 : Lancer le garde-fou — vert**

Run: `.venv/bin/pytest tests/test_runtime_messages_english.py -q`
Expected : PASS (1 test).

- [ ] **Step 3 : Prouver la non-vacuité (sans modifier le dépôt)**

Run:
```bash
.venv/bin/python - <<'PY'
import importlib.util, ast
spec = importlib.util.spec_from_file_location("g", "tests/test_runtime_messages_english.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
# injecte un faux offender en mémoire : un raise accentué
tree = ast.parse('raise ValueError("règle invalide")')
print("offenders sur code accentué:", g._accented(tree.body[0].exc))  # doit être non vide
PY
```
Expected : `offenders sur code accentué: ['règle invalide']` (le détecteur n'est pas trivial).

- [ ] **Step 4 : Suite complète**

Run: `.venv/bin/pytest -q`
Expected : 202 passed (201 + le garde-fou).

- [ ] **Step 5 : Commit**

```bash
git add tests/test_runtime_messages_english.py
git commit -m "test: garde-fou anti-regression messages operateur en anglais (AST)"
```

---

## Auto-revue du plan (checklist auteur)

**Couverture du spec :**
- Chantier 1 (sweep messages opérateur → anglais) → Tasks 1-4. ✅
- Chantier 2 (garde-fou AST) → Task 5. ✅
- Hors périmètre (docstrings/commentaires/prompts LLM/descriptions/vocab classifier/regex/doc bilingue) → protégé par construction + rappelé dans Global Constraints et les steps. ✅
- Tests couplés (assertion FR) → traité dans Global Constraints (`terminé` = fixture, non impacté) + consigne de mise à jour par tâche. ✅
- Non-régression 201 tests → Step 3/4 de chaque tâche. ✅

**Raffinement acté vs spec** : le garde-fou couvre **raise/log/print + `reason=`/`error=`** (le spec disait « raise/log/print ») — surensemble strict de ce qui est traduit (les 4-18 réponses structurées opérateur : `loop.py` reasons, `server.py` error, réponses agents), zéro faux positif réaliste. À signaler à l'humain au handoff.

**Placeholders** : aucun — T1/T2 ont les traductions exactes ; T3/T4 pointent l'inventaire exhaustif (fichier:ligne) + tables représentatives + glossaire + oracle mécanique (scan par couche + garde-fou). La traduction est un travail de jugement borné par le glossaire et vérifié mécaniquement.

**Cohérence des types** : aucune signature touchée (uniquement contenu de littéraux). Le garde-fou et le scan par couche partagent la même logique AST (raise/log/print + reason/error).

**Découpage** : par couche, chaque tâche testable seule (scan couche = 0 + suite verte) ; garde-fou en dernier, vert d'emblée (pas de xfail).
