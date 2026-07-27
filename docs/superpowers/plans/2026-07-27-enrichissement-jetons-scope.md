# Enrichissement des jetons par `scope` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Attacher aux jetons IP une classification non-sensible (`scope`), l'exposer au proposer LLM (légende) et au moteur de politique (pseudo-args synthétiques), sans jamais révéler l'adresse.

**Architecture :** Le `Vault` calcule `scope` à la tokenisation (`ipaddress` stdlib) ; `decide` augmente les args (`ip__scope`) pour `evaluate` seulement (moteur inchangé, intention auditée/exécutée = originale) ; la boucle passe une légende `jeton→scope` au proposer.

**Tech Stack :** Python 3.11, stdlib `ipaddress` (aucune dépendance nouvelle), pydantic (existant), pytest.

## Global Constraints

- **Zéro-secret** : `scope` est une classe dérivée, jamais la valeur. La valeur réelle ne quitte le vault qu'à `core/execution/boundary.py`. Ni la légende LLM ni les pseudo-args ne contiennent l'adresse.
- **Fail-closed inchangé** : défaut `deny` ; `evaluate` (`core/policy/engine.py`) **ne change pas**.
- **Aucune clé synthétique ne fuit** : l'`Intention` portée par le `Verdict`, l'audit et l'exécution ne contiennent **que** les vrais args (jetons). L'augmentation `ip__scope` n'existe que le temps du match.
- **Rétrocompatible** : `arg_meta` optionnel (`None` par défaut) ; `context` du proposer optionnel (`""`) ⇒ prompt identique ; règles existantes inchangées ; snapshot de session compatible (nouveau champ `meta` toléré à l'absence).
- **Aucune dépendance nouvelle** (`ipaddress` stdlib). Déterministe, fonctions pures testables.
- **Dépôt** : `cyber-agent-engine` (GitHub, branche `feat/token-scope-enrichment`). En-tête `# SPDX-License-Identifier: AGPL-3.0-or-later` **uniquement si un nouveau fichier est créé** (ici : que des modifications de fichiers existants → pas de nouvel en-tête). Commits Conventional Commits **en français**, **sans** mention IA/Co-Authored-By. Lancer les tests : `pytest` (ou `python -m pytest`). `ruff` + `mypy` doivent rester clean sur la surface touchée.

## Constantes / classes de `scope`

`public` (global) · `private` (RFC1918 + ULA `fc00::/7`) · `loopback` · `link_local` · `reserved` · `None` (valeur non parsable en IP/subnet). Séparateur de pseudo-arg : `__` (`<arg>__<clé_meta>`).

---

## File Structure

- `core/tokens/vault.py` (modifié) — `classify_ip` + meta dans `Vault` + snapshot/restore.
- `core/tokens/__init__.py` (modifié) — exporter `classify_ip` si utile.
- `core/decision.py` (modifié) — `decide(..., arg_meta=None)` + augmentation pour `evaluate`.
- `core/orchestrator.py` (modifié) — même param `arg_meta` (DRY mono-action).
- `coordinator/proposer.py` (modifié) — `propose(..., *, context="")` + protocole.
- `coordinator/loop.py` (modifié) — `_legend`, `_arg_meta`, câblage vers propose + decide.
- `tests/` — nouveaux tests par tâche (suivre l'emplacement des tests existants du module).

---

## Task 1 : `core/tokens/vault.py` — `classify_ip` + meta de jeton

**Files:**
- Modify: `core/tokens/vault.py`
- Modify: `core/tokens/__init__.py`
- Test: `tests/` (fichier des tests vault existants — sinon `tests/test_tokens_scope.py`)

**Interfaces:**
- Produces : `classify_ip(value: str) -> str | None` (pur, stdlib) ·
  `Vault.token_for` renseigne `self._meta[token] = {"scope": s}` pour `label ∈ {"IP_ADDRESS","IP_SUBNET"}` quand `classify_ip` ≠ None ·
  `Vault.meta(token: str) -> dict[str, str]` · `Vault.meta_items() -> dict[str, dict[str, str]]` ·
  `snapshot()` inclut `"meta"` ; `restore()` le relit (défaut `{}`).

- [ ] **Step 1 : Écrire les tests (échouent)**

Créer/étendre les tests du module tokens :
```python
from core.tokens.vault import Vault, classify_ip, tokenize

def test_classify_ip_classes():
    assert classify_ip("8.8.8.8") == "public"
    assert classify_ip("10.1.2.3") == "private"
    assert classify_ip("192.168.1.1") == "private"
    assert classify_ip("172.16.0.1") == "private"
    assert classify_ip("127.0.0.1") == "loopback"
    assert classify_ip("169.254.1.1") == "link_local"
    assert classify_ip("fd00::1") == "private"        # ULA
    assert classify_ip("2620:fe::9") == "public"
    assert classify_ip("10.0.0.0/8") == "private"     # subnet CIDR
    assert classify_ip("pas-une-ip") is None
    assert classify_ip("") is None
    # ⚠️ NE PAS asserter les plages de documentation RFC5737 (192.0.2/24, 198.51.100/24,
    # 203.0.113/24 — l'IP du démo !) : leur is_private/is_global varie selon la version de
    # Python. L'implémenteur DOIT vérifier le retour réel de classify_ip sur 203.0.113.45
    # (probablement "reserved" ou "private" selon la version) et documenter la valeur
    # observée — sans deviner. Idem 192.0.2.1.

def test_vault_stores_scope_for_ip_only():
    v = Vault()
    tok_ip = v.token_for("IP_ADDRESS", "10.0.0.5")
    tok_sub = v.token_for("IP_SUBNET", "192.168.0.0/24")
    tok_host = v.token_for("HOSTNAME", "example.com")
    assert v.meta(tok_ip) == {"scope": "private"}
    assert v.meta(tok_sub) == {"scope": "private"}
    assert v.meta(tok_host) == {}                      # pas de scope pour un hostname
    assert v.meta("INEXISTANT_1") == {}

def test_meta_survives_snapshot_restore():
    v = Vault()
    tok = v.token_for("IP_ADDRESS", "8.8.8.8")
    v2 = Vault.restore(v.snapshot())
    assert v2.meta(tok) == {"scope": "public"}
    assert v2.resolve(tok) == "8.8.8.8"

def test_meta_never_contains_value():
    v = Vault()
    v.token_for("IP_ADDRESS", "203.0.113.45")
    dumped = str(v.meta_items())
    assert "203.0.113.45" not in dumped               # zéro-secret : la classe, pas la valeur
```

- [ ] **Step 2 : Lancer (échoue)**

Run : `python -m pytest tests/ -q -k "classify or scope or meta"`
Expected : FAIL (`classify_ip` absent, `meta` absent).

- [ ] **Step 3 : Implémenter**

Dans `core/tokens/vault.py`, ajouter la fonction pure (avant la classe) :
```python
import ipaddress


def classify_ip(value: str) -> str | None:
    """Classe non-sensible d'une IP ou d'un subnet CIDR (pur, stdlib). None si non parsable."""
    obj: ipaddress._BaseAddress | ipaddress._BaseNetwork | None = None
    try:
        obj = ipaddress.ip_address(value)
    except ValueError:
        try:
            obj = ipaddress.ip_network(value, strict=False)
        except ValueError:
            return None
    if obj.is_loopback:
        return "loopback"
    if obj.is_link_local:
        return "link_local"
    if obj.is_private:
        return "private"
    if obj.is_global:
        return "public"
    return "reserved"
```
Dans `Vault.__init__`, ajouter `self._meta: dict[str, dict[str, str]] = {}`.
Dans `Vault.token_for`, **après** avoir créé/récupéré le jeton, calculer le meta (une seule
fois par jeton neuf) :
```python
        if label in ("IP_ADDRESS", "IP_SUBNET") and token not in self._meta:
            scope = classify_ip(value)
            if scope is not None:
                self._meta[token] = {"scope": scope}
```
(placer ce bloc sur le chemin où `token` vient d'être créé — pas sur le retour anticipé
`existing`, pour ne pas recalculer ; mais un jeton réutilisé garde son meta.)
Ajouter les accesseurs :
```python
    def meta(self, token: str) -> dict[str, str]:
        return dict(self._meta.get(token, {}))

    def meta_items(self) -> dict[str, dict[str, str]]:
        return {k: dict(v) for k, v in self._meta.items()}
```
Étendre `snapshot()` → ajouter `"meta": {k: dict(v) for k, v in self._meta.items()}`.
Étendre `restore()` → `v._meta = {k: dict(val) for k, val in snap.get("meta", {}).items()}`.
Exporter dans `core/tokens/__init__.py` : ajouter `classify_ip` à l'import + `__all__`.

- [ ] **Step 4 : Lancer (passent) + suite tokens complète**

Run : `python -m pytest tests/ -q -k "token or vault or classify or scope or meta"`
Expected : PASS (nouveaux + existants verts).

- [ ] **Step 5 : Commit + push**

```bash
git add core/tokens/vault.py core/tokens/__init__.py tests/
git commit -m "feat(tokens): classifier scope (public/private/…) et le porter sur le jeton"
git push
```

---

## Task 2 : `core/decision.py` — augmentation `arg_meta` (moteur inchangé)

**Files:**
- Modify: `core/decision.py`
- Modify: `core/orchestrator.py`
- Test: `tests/` (tests de décision existants — sinon `tests/test_decision_scope.py`)

**Interfaces:**
- Consumes : `core/policy/engine.evaluate` (inchangé), `core/policy/models` (`Intention`, `Verdict`).
- Produces : `decide(intention, *, catalog, policy, sink, arg_meta: dict[str, dict[str, str]] | None = None, event="policy_decision") -> Verdict`.
  Augmente une **copie** de l'intention (`args ∪ {f"{arg}__{k}": v}`) pour `evaluate`
  UNIQUEMENT ; le `Verdict` renvoyé et l'entrée d'audit portent l'**intention originale**.
  `core/orchestrator.py` accepte le même `arg_meta` optionnel.

- [ ] **Step 1 : Écrire les tests (échouent)**

```python
from core.decision import decide
from core.policy.models import Intention, Rule, Match, ArgMatch
from core.policy.catalog import CapabilityCatalog   # adapter aux fixtures existantes
# ... construire un catalog validant opnsense.block_ip(ip) + un sink en mémoire (cf. tests existants)

def test_deny_on_private_scope(catalog, sink):
    rule = Rule(match=Match(capability="opnsense.block_*",
                            args={"ip__scope": ArgMatch(op="eq", value="private")}),
                effect="deny", reason="ip privée")
    intention = Intention(capability="opnsense.block_ip", args={"ip": "IP_ADDRESS_1"})
    v = decide(intention, catalog=catalog, policy=[rule], sink=sink,
               arg_meta={"ip": {"scope": "private"}})
    assert v.effect == "deny"
    # aucune clé synthétique ne fuit dans l'intention du verdict
    assert "ip__scope" not in v.intention.args
    assert v.intention.args == {"ip": "IP_ADDRESS_1"}

def test_public_scope_not_denied_by_private_rule(catalog, sink):
    rule = Rule(match=Match(capability="opnsense.block_*",
                            args={"ip__scope": ArgMatch(op="eq", value="private")}),
                effect="deny")
    allow = Rule(match=Match(capability="opnsense.block_*"), effect="approve")
    intention = Intention(capability="opnsense.block_ip", args={"ip": "IP_ADDRESS_1"})
    v = decide(intention, catalog=catalog, policy=[rule, allow], sink=sink,
               arg_meta={"ip": {"scope": "public"}})
    assert v.effect == "approve"

def test_backward_compatible_without_arg_meta(catalog, sink):
    allow = Rule(match=Match(capability="opnsense.block_*"), effect="approve")
    intention = Intention(capability="opnsense.block_ip", args={"ip": "IP_ADDRESS_1"})
    v = decide(intention, catalog=catalog, policy=[allow], sink=sink)   # pas d'arg_meta
    assert v.effect == "approve" and v.intention.args == {"ip": "IP_ADDRESS_1"}
```
(Réutiliser les fixtures catalog/sink des tests de décision existants ; adapter les imports.)

- [ ] **Step 2 : Lancer (échoue)**

Run : `python -m pytest tests/ -q -k "scope and (decide or decision)"`
Expected : FAIL (`decide` n'accepte pas `arg_meta`).

- [ ] **Step 3 : Implémenter**

Dans `core/decision.py`, modifier `decide` :
```python
def decide(
    intention: Intention,
    *,
    catalog: CapabilityCatalog,
    policy: list[Rule],
    sink: AuditSink,
    arg_meta: dict[str, dict[str, str]] | None = None,
    event: str = "policy_decision",
) -> Verdict:
    catalog.validate_intention(intention)
    if arg_meta:
        synthetic = {f"{arg}__{k}": v for arg, m in arg_meta.items() for k, v in m.items()}
        augmented = intention.model_copy(update={"args": {**intention.args, **synthetic}})
    else:
        augmented = intention
    raw = evaluate(augmented, policy)
    # Le verdict/l'audit portent l'intention ORIGINALE (aucune clé synthétique).
    verdict = Verdict(effect=raw.effect, matched_rule=raw.matched_rule, intention=intention)
    sink.write(entry_from_verdict(verdict, event=event))
    return verdict
```
NB : `catalog.validate_intention` s'exécute sur l'intention **originale** (les pseudo-args
ne sont pas de vrais args du catalogue — ne jamais les valider ni les exécuter).
Répliquer le param `arg_meta` dans `core/orchestrator.py` là où il appelle `decide` (le
passer tel quel ; défaut `None`). Lire le fichier pour la signature exacte.

- [ ] **Step 4 : Lancer (passent) + suite décision/politique**

Run : `python -m pytest tests/ -q -k "decide or decision or policy or orchestrator"`
Expected : PASS (nouveaux + existants ; `engine.evaluate` inchangé, aucune régression).

- [ ] **Step 5 : Commit + push**

```bash
git add core/decision.py core/orchestrator.py tests/
git commit -m "feat(policy): decide augmente les args (pseudo-args scope) sans polluer audit/exécution"
git push
```

---

## Task 3 : `coordinator/proposer.py` — légende de contexte au prompt

**Files:**
- Modify: `coordinator/proposer.py`
- Test: `tests/` (tests proposer existants — sinon `tests/test_proposer_context.py`)

**Interfaces:**
- Produces : `LlmProposer.propose(request_tokens, history, *, context: str = "") -> Proposal`.
  Si `context` non vide, insère un message système additionnel avant l'observation.
  Le protocole `ProposerLike` (dans `coordinator/loop.py`) gagne le même paramètre optionnel.

- [ ] **Step 1 : Écrire le test (échoue)**

```python
import pytest
from coordinator.proposer import LlmProposer
# catalog minimal validant opnsense.block_ip(ip) ; ChatLLM mock qui capture les messages

class _CaptureLLM:
    def __init__(self): self.last = None
    async def chat(self, messages, max_tokens=1024):
        self.last = messages
        return '{"action": {"capability": "opnsense.block_ip", "args": {"ip": "IP_ADDRESS_1"}}}'

@pytest.mark.asyncio
async def test_context_legend_injected(catalog):
    llm = _CaptureLLM()
    p = LlmProposer(llm=llm, catalog=catalog)
    await p.propose("bloque IP_ADDRESS_1", [], context="IP_ADDRESS_1 = IPv4 public")
    blob = " ".join(m["content"] for m in llm.last)
    assert "IP_ADDRESS_1 = IPv4 public" in blob

@pytest.mark.asyncio
async def test_no_context_unchanged(catalog):
    llm = _CaptureLLM()
    p = LlmProposer(llm=llm, catalog=catalog)
    await p.propose("bloque IP_ADDRESS_1", [])          # sans context
    blob = " ".join(m["content"] for m in llm.last)
    assert "Contexte des jetons" not in blob
```
(`asyncio_mode` : suivre la config pytest du repo ; sinon `@pytest.mark.asyncio`.)

- [ ] **Step 2 : Lancer (échoue)**

Run : `python -m pytest tests/ -q -k "context or proposer"`
Expected : FAIL (`propose` n'accepte pas `context`).

- [ ] **Step 3 : Implémenter**

Dans `coordinator/proposer.py` :
- `_base_messages(self, request_tokens, history, context="")` : si `context`, insérer après
  le message système un message `{"role": "system", "content": "Contexte des jetons (non
  sensible, indicatif) : " + context}`.
- `propose(self, request_tokens, history, *, context="")` : passer `context` aux deux appels
  `_base_messages` (initial + relance).
- Compléter `_SYSTEM` d'une phrase : le contexte des jetons est **indicatif** (nature de la
  valeur), jamais une valeur réelle à recopier ni une autorisation.
Mettre à jour le protocole `ProposerLike` dans `coordinator/loop.py` :
`async def propose(self, request_tokens: str, history: list[str], *, context: str = "") -> Proposal: ...`

- [ ] **Step 4 : Lancer (passent)**

Run : `python -m pytest tests/ -q -k "context or proposer"`
Expected : PASS.

- [ ] **Step 5 : Commit + push**

```bash
git add coordinator/proposer.py coordinator/loop.py tests/
git commit -m "feat(coordinator): légende token→scope optionnelle au prompt du proposer"
git push
```

---

## Task 4 : `coordinator/loop.py` — câblage légende + `arg_meta`

**Files:**
- Modify: `coordinator/loop.py`
- Test: `tests/` (tests de boucle existants — sinon `tests/test_loop_scope.py`)

**Interfaces:**
- Consumes : `Vault.meta_items`/`meta` (T1), `decide(arg_meta=)` (T2), `propose(context=)` (T3).
- Produces : `_legend(vault) -> str` (lignes `JETON = <humain>` depuis `meta_items`, vide si aucun) ·
  `_arg_meta(intention, vault) -> dict[str, dict[str, str]]` (pour chaque `arg→jeton` ayant un meta) ·
  la boucle passe `context=_legend(...)` à `propose` et `arg_meta=_arg_meta(...)` à `decide`.

- [ ] **Step 1 : Écrire le test (échoue)**

Test d'intégration boucle (réutiliser les fakes des tests de boucle existants : proposer
factice, sink, session store, agent call factice) :
```python
# proposer factice qui propose block_ip(IP_ADDRESS_1) ; vault peuplé via la requête réelle
# politique : deny si ip__scope == private
@pytest.mark.asyncio
async def test_loop_denies_private_ip(loop_factory):
    loop = loop_factory(policy=[deny_private_rule, approve_block_rule])
    result = await loop.execute("bloque 10.0.0.5", history=[])
    assert result.effect_or_status == "denied"   # adapter au type de retour réel (Failed/verdict)

@pytest.mark.asyncio
async def test_loop_gates_public_ip(loop_factory):
    loop = loop_factory(policy=[deny_private_rule, approve_block_rule])
    result = await loop.execute("bloque 8.8.8.8", history=[])
    assert "pending_approval" in str(result).lower()  # adapter à la forme réelle (Suspended)
```
(Adapter aux types de retour réels de la boucle — lire `loop.py` : `Suspended`/`Failed`/… ;
l'essentiel testé : `10.0.0.5` (private) → refusé avant gate ; `8.8.8.8` (public) → gate.)

- [ ] **Step 2 : Lancer (échoue)**

Run : `python -m pytest tests/ -q -k "loop and scope"`
Expected : FAIL (légende/arg_meta pas encore câblés).

- [ ] **Step 3 : Implémenter**

Lire `coordinator/loop.py` (le point où `self._proposer.propose(request_tokens, history)` et
`decide(...)` sont appelés — cf. `_run`). Ajouter :
```python
    def _legend(self, vault: Vault) -> str:
        lines = []
        for token, m in vault.meta_items().items():
            scope = m.get("scope")
            if scope:
                fam = "IPv6" if ":" in (vault.resolve(token) or "") else "IPv4"
                lines.append(f"{token} = {fam} {scope}")
        return " ; ".join(lines)

    def _arg_meta(self, intention: Intention, vault: Vault) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for arg, tok in intention.args.items():
            m = vault.meta(tok)
            if m:
                out[arg] = m
        return out
```
Au point d'appel : `proposal = await self._proposer.propose(request_tokens, history, context=self._legend(vault))`
et pour la décision : `verdict = decide(intention, catalog=…, policy=…, sink=…, arg_meta=self._arg_meta(intention, vault))`.
(Respecter la signature réelle de `decide` telle qu'appelée aujourd'hui ; n'ajouter que `arg_meta`.)

- [ ] **Step 4 : Lancer (passent) + suite complète**

Run : `python -m pytest -q`
Expected : PASS (toute la suite ; rien de régressé). Vérifier `ruff check .` et `mypy` sur la surface touchée si le repo les exécute en CI.

- [ ] **Step 5 : Commit + push**

```bash
git add coordinator/loop.py tests/
git commit -m "feat(coordinator): câble la légende scope (proposer) et les pseudo-args (politique) dans la boucle"
git push
```

---

## Notes de séquencement

- **T1** (vault) est le socle (pur, indépendant). **T2** (decide) et **T3** (proposer) en
  dépendent conceptuellement mais sont testables isolément avec des fakes. **T4** câble tout
  dans la boucle et fournit le test d'intégration bout-en-bout.
- **`core/policy/engine.py` ne doit PAS être modifié** (contrainte de conception) — toute la
  logique de pseudo-args vit dans `decide` (T2).
- Vérifier à chaque tâche que l'**intention originale** (jetons seuls) est ce qui est audité
  et exécuté — jamais les clés `__scope`.
- Chaque commit poussé sur `feat/token-scope-enrichment` ; PR/merge vers `main` à la revue finale.
