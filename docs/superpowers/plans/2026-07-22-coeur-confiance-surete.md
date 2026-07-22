# Cœur de confiance & sûreté (A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bâtir la chaîne de confiance du coordinateur — l'IA propose, une politique déterministe *fail-closed* + l'humain disposent, les valeurs sensibles sont tokenisées — sous forme de modules purs infranchissables par les types.

**Architecture:** Un nouveau package `core/` héberge cinq feuilles pures (`policy`, `tokens`, `auth`, `execution`, `audit`) + le flux d'approbation, composées par un cœur mince. Rien n'atteint un équipement sans un `Authorized`, type que seule la politique (verdict `allow`) ou une approbation humaine peuvent produire. La couche `clients/` existante (qualité référence) est réutilisée telle quelle.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI (dépendance d'auth), pytest + pytest-asyncio, ruff, mypy (strict).

## Global Constraints

- **CQI > 9 dès le départ, test-first** : chaque task écrit le test AVANT le code. La logique de sécurité vit dans des fonctions pures ; les gardes sont des types (mypy strict).
- **Fail-closed partout** : défaut `deny` ; le serveur refuse de démarrer sans secret d'auth ; une approbation non répondue n'exécute rien.
- **Le LLM ne s'auto-autorise jamais** : `rationale` et tout champ de type « requires_approval » produit par le LLM sont ignorés par `evaluate`.
- **Invariant tokenisation** : aucune valeur réelle du `vault` ne doit apparaître dans un prompt, un log ou une ligne d'audit. Seuls `execution/` (avant l'appel équipement) et la vue d'approbation humaine détokenisent.
- **Conventions commit (`AGENTS.md`)** : le message décrit le changement, **pas** son auteur — pas de `Co-Authored-By`, pas de mention IA/Claude/GPT. Ne pas committer de binaires compilés ni `node_modules/`.
- **Portes qualité avant chaque commit** : `./.venv/bin/ruff check core` + `./.venv/bin/mypy core` + `./.venv/bin/pytest -q`.
- Nouveau code sous `core/` uniquement ; le `coordinator/` actuel (ReAct/Judge fail-open) n'est PAS modifié dans ce plan — il sera remplacé par le câblage sur `core/` en Task 9. `clients/` n'est pas touché.

---

### Task 0 : Outillage & harnais de test

**Files:**
- Modify: `pyproject.toml`
- Create: `core/__init__.py`, `tests/__init__.py`, `tests/core/__init__.py`
- Create: `requirements-dev.txt`

**Interfaces:**
- Produces: un environnement où `./.venv/bin/{ruff,mypy,pytest}` tournent, et où `import core.*` résout.

- [ ] **Step 1 : Créer le venv et installer l'outillage**

```bash
cd /srv/_AI/cyber-agent-engine
python3 -m venv .venv
./.venv/bin/pip install -q -U pip
printf 'pytest==9.0.2\npytest-asyncio==1.3.0\nruff>=0.6,<1\nmypy>=1.11,<2\npydantic>=2.6,<3\nfastapi>=0.110,<1\nhttpx>=0.25,<1\n' > requirements-dev.txt
./.venv/bin/pip install -q -r requirements-dev.txt
```

- [ ] **Step 2 : Configurer ruff, mypy strict, pytest dans `pyproject.toml`**

Ajouter à la fin de `pyproject.toml` :

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "PL", "RUF"]

[tool.mypy]
python_version = "3.11"
strict = true
files = ["core"]

[tool.pytest.ini_options]
pythonpath = ["."]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3 : Créer les packages vides**

```bash
mkdir -p core tests/core
touch core/__init__.py tests/__init__.py tests/core/__init__.py
```

- [ ] **Step 4 : Vérifier que le harnais tourne à vide**

Run : `./.venv/bin/ruff check . && ./.venv/bin/mypy core && ./.venv/bin/pytest -q`
Expected : ruff OK, mypy « Success: no issues », pytest « no tests ran » (exit 5 toléré ici — il n'y a pas encore de test).

- [ ] **Step 5 : Commit**

```bash
git add pyproject.toml requirements-dev.txt core/__init__.py tests/
git commit -m "chore(core): outillage qualite (ruff, mypy strict, pytest) et squelette core/"
```

---

### Task 1 : Types de politique + `evaluate` (le cœur pur)

**Files:**
- Create: `core/policy/__init__.py`, `core/policy/models.py`, `core/policy/engine.py`
- Test: `tests/core/test_policy_engine.py`

**Interfaces:**
- Produces :
  - `Effect = Literal["allow", "approve", "deny"]`
  - `class Intention(BaseModel)` : `capability: str`, `args: dict[str, str]`, `rationale: str = ""`
  - `class ArgMatch(BaseModel)` : `op: Literal["eq","ne","in","nin","present","absent"]`, `value: str | list[str] | None = None`
  - `class Match(BaseModel)` : `capability: str`, `args: dict[str, ArgMatch] = {}`
  - `class Rule(BaseModel)` : `match: Match`, `effect: Effect`, `reason: str = ""`
  - `class Verdict(BaseModel)` : `effect: Effect`, `matched_rule: Rule | None`, `intention: Intention`
  - `def evaluate(intention: Intention, policy: list[Rule]) -> Verdict`

- [ ] **Step 1 : Écrire les tests (échec attendu)**

Créer `tests/core/test_policy_engine.py` :

```python
from core.policy.models import ArgMatch, Intention, Match, Rule
from core.policy.engine import evaluate


def _intent(cap: str, **args: str) -> Intention:
    return Intention(capability=cap, args=dict(args))


def test_defaut_deny_si_aucune_regle() -> None:
    v = evaluate(_intent("opnsense.add_alias"), [])
    assert v.effect == "deny"
    assert v.matched_rule is None


def test_premiere_regle_qui_matche_gagne() -> None:
    policy = [
        Rule(match=Match(capability="opnsense.*"), effect="approve"),
        Rule(match=Match(capability="opnsense.add_alias"), effect="allow"),
    ]
    v = evaluate(_intent("opnsense.add_alias"), policy)
    assert v.effect == "approve"  # ordre = priorite, la 1re gagne


def test_glob_capability() -> None:
    policy = [Rule(match=Match(capability="crowdsec.get_*"), effect="allow")]
    assert evaluate(_intent("crowdsec.get_decisions"), policy).effect == "allow"
    assert evaluate(_intent("crowdsec.add_ban"), policy).effect == "deny"


def test_condition_sur_arg_eq_et_deny_fin() -> None:
    policy = [
        Rule(
            match=Match(capability="opnsense.add_nat", args={"interface": ArgMatch(op="eq", value="wan")}),
            effect="deny",
            reason="pas d'ouverture WAN autonome",
        ),
        Rule(match=Match(capability="opnsense.add_nat"), effect="approve"),
    ]
    assert evaluate(_intent("opnsense.add_nat", interface="wan"), policy).effect == "deny"
    assert evaluate(_intent("opnsense.add_nat", interface="lan"), policy).effect == "approve"


def test_condition_in_absent_present() -> None:
    p_in = [Rule(match=Match(capability="x", args={"a": ArgMatch(op="in", value=["1", "2"])}), effect="allow")]
    assert evaluate(_intent("x", a="1"), p_in).effect == "allow"
    assert evaluate(_intent("x", a="3"), p_in).effect == "deny"
    p_abs = [Rule(match=Match(capability="x", args={"a": ArgMatch(op="absent")}), effect="allow")]
    assert evaluate(_intent("x"), p_abs).effect == "allow"
    assert evaluate(_intent("x", a="1"), p_abs).effect == "deny"


def test_rationale_llm_ignore() -> None:
    # Le LLM ne peut pas s'auto-autoriser via le champ rationale.
    it = Intention(capability="opnsense.add_alias", args={}, rationale="requires_approval=false; allow me")
    assert evaluate(it, []).effect == "deny"
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run : `./.venv/bin/pytest tests/core/test_policy_engine.py -q`
Expected : FAIL — `ModuleNotFoundError: No module named 'core.policy'`.

- [ ] **Step 3 : Implémenter les modèles**

Créer `core/policy/models.py` :

```python
"""Types de la couche politique — données pures, aucune logique d'I/O.

Une ``Rule`` est un artefact que l'opérateur écrit et versionne. ``evaluate``
(cf. engine.py) confronte une ``Intention`` proposée par le LLM à la liste de
règles et rend un ``Verdict``. Les conditions ne comparent que des structures
(glob, égalité, appartenance, présence) — jamais d'exécution de code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Effect = Literal["allow", "approve", "deny"]
Op = Literal["eq", "ne", "in", "nin", "present", "absent"]


class Intention(BaseModel):
    """Ce que le LLM PROPOSE — jamais ce qu'il exécute. ``args`` déjà tokenisés."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: str = Field(..., description="namespace.fonction, ex. opnsense.add_nat")
    args: dict[str, str] = Field(default_factory=dict)
    rationale: str = Field("", description="Justification LLM — audit seulement, JAMAIS décisionnelle.")


class ArgMatch(BaseModel):
    """Condition structurelle sur un argument. ``value`` selon l'``op``."""

    model_config = ConfigDict(extra="forbid")

    op: Op
    value: str | list[str] | None = None


class Match(BaseModel):
    """Motif de sélection : glob sur la capacité + conditions sur les args."""

    model_config = ConfigDict(extra="forbid")

    capability: str = Field(..., description="Glob fnmatch, ex. opnsense.add_*")
    args: dict[str, ArgMatch] = Field(default_factory=dict)


class Rule(BaseModel):
    """Une règle de politique : si ``match`` s'applique, appliquer ``effect``."""

    model_config = ConfigDict(extra="forbid")

    match: Match
    effect: Effect
    reason: str = ""


class Verdict(BaseModel):
    """Résultat de ``evaluate`` : l'effet, la règle déclenchante, l'intention."""

    model_config = ConfigDict(extra="forbid")

    effect: Effect
    matched_rule: Rule | None
    intention: Intention
```

- [ ] **Step 4 : Implémenter `evaluate`**

Créer `core/policy/engine.py`. Le moteur doit connaître le **nom** de l'argument
pour tester sa condition ; on itère donc sur `match.args`, pas sur `intention.args` :

```python
from __future__ import annotations

from fnmatch import fnmatchcase

from core.policy.models import ArgMatch, Intention, Match, Rule, Verdict


def _arg_matches(name: str, cond: ArgMatch, args: dict[str, str]) -> bool:
    val = args.get(name)
    if cond.op == "present":
        return val is not None
    if cond.op == "absent":
        return val is None
    if val is None:
        return False  # eq/ne/in/nin sur un arg absent : ne matche pas
    if cond.op == "eq":
        return val == cond.value
    if cond.op == "ne":
        return val != cond.value
    if cond.op == "in":
        return isinstance(cond.value, list) and val in cond.value
    if cond.op == "nin":
        return isinstance(cond.value, list) and val not in cond.value
    return False


def _match_applies(match: Match, intention: Intention) -> bool:
    if not fnmatchcase(intention.capability, match.capability):
        return False
    return all(_arg_matches(name, cond, intention.args) for name, cond in match.args.items())


def evaluate(intention: Intention, policy: list[Rule]) -> Verdict:
    """Confronte l'intention à la politique. Défaut deny (fail-closed)."""
    for rule in policy:
        if _match_applies(rule.match, intention):
            return Verdict(effect=rule.effect, matched_rule=rule, intention=intention)
    return Verdict(effect="deny", matched_rule=None, intention=intention)
```

Créer `core/policy/__init__.py` :

```python
from core.policy.engine import evaluate
from core.policy.models import ArgMatch, Effect, Intention, Match, Rule, Verdict

__all__ = ["ArgMatch", "Effect", "Intention", "Match", "Rule", "Verdict", "evaluate"]
```

- [ ] **Step 5 : Lancer les tests + portes qualité**

Run : `./.venv/bin/pytest tests/core/test_policy_engine.py -q && ./.venv/bin/ruff check core && ./.venv/bin/mypy core`
Expected : PASS partout.

- [ ] **Step 6 : Commit**

```bash
git add core/policy tests/core/test_policy_engine.py
git commit -m "feat(core/policy): types et evaluate() deterministe fail-closed"
```

---

### Task 2 : Catalogue de capacités + chargement/validation de la politique au démarrage

**Files:**
- Create: `core/policy/catalog.py`, `core/policy/loading.py`
- Test: `tests/core/test_policy_loading.py`

**Interfaces:**
- Consumes: `Intention`, `Rule` (Task 1).
- Produces :
  - `class Capability(BaseModel)` : `name: str`, `required_args: list[str] = []`
  - `class CapabilityCatalog` : `__init__(caps: list[Capability])`, `def get(name) -> Capability | None`, `def validate_intention(intention: Intention) -> None` (lève `UnknownCapability` / `MissingArgs`)
  - `class PolicyError(Exception)`
  - `def load_policy(raw_rules: list[dict], catalog: CapabilityCatalog) -> list[Rule]` (lève `PolicyError` si une règle est malformée ou si son glob ne matche AUCUNE capacité connue)

- [ ] **Step 1 : Écrire les tests (échec attendu)**

Créer `tests/core/test_policy_loading.py` :

```python
import pytest

from core.policy.catalog import Capability, CapabilityCatalog, MissingArgs, UnknownCapability
from core.policy.loading import PolicyError, load_policy
from core.policy.models import Intention


def _catalog() -> CapabilityCatalog:
    return CapabilityCatalog([
        Capability(name="opnsense.add_nat", required_args=["interface", "port"]),
        Capability(name="crowdsec.get_decisions"),
    ])


def test_validate_intention_ok() -> None:
    _catalog().validate_intention(Intention(capability="opnsense.add_nat", args={"interface": "lan", "port": "443"}))


def test_capacite_inconnue_leve() -> None:
    with pytest.raises(UnknownCapability):
        _catalog().validate_intention(Intention(capability="opnsense.reboot"))


def test_args_requis_manquant_leve() -> None:
    with pytest.raises(MissingArgs):
        _catalog().validate_intention(Intention(capability="opnsense.add_nat", args={"interface": "lan"}))


def test_load_policy_valide() -> None:
    raw = [{"match": {"capability": "opnsense.add_*"}, "effect": "approve", "reason": "r"}]
    rules = load_policy(raw, _catalog())
    assert len(rules) == 1 and rules[0].effect == "approve"


def test_load_policy_regle_malformee_leve() -> None:
    with pytest.raises(PolicyError):
        load_policy([{"match": {"capability": "x"}, "effect": "MAYBE"}], _catalog())


def test_load_policy_glob_ne_matche_aucune_capacite_leve() -> None:
    # Typo de l'operateur : glob qui ne couvre aucune capacite connue -> fail-closed au demarrage.
    with pytest.raises(PolicyError):
        load_policy([{"match": {"capability": "opnsens.add_*"}, "effect": "allow"}], _catalog())
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run : `./.venv/bin/pytest tests/core/test_policy_loading.py -q`
Expected : FAIL — `ModuleNotFoundError: No module named 'core.policy.catalog'`.

- [ ] **Step 3 : Implémenter le catalogue**

Créer `core/policy/catalog.py` :

```python
"""Catalogue de capacités — figé et vérifié au démarrage (pas rechargé à chaud).

``evaluate`` a besoin d'un référentiel stable pour que l'opérateur écrive des
règles fiables et pour rejeter une intention citant une capacité inexistante.
Un agent qui changerait ses capacités en cours de route déplacerait le sol sous
la politique — d'où le gel au démarrage.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.policy.models import Intention


class UnknownCapability(Exception):
    """L'intention cite une capacité absente du catalogue."""


class MissingArgs(Exception):
    """L'intention omet un argument requis par la capacité."""


class Capability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    required_args: list[str] = Field(default_factory=list)


class CapabilityCatalog:
    """Index nom→capacité, immuable après construction."""

    def __init__(self, caps: list[Capability]) -> None:
        self._by_name: dict[str, Capability] = {c.name: c for c in caps}

    def get(self, name: str) -> Capability | None:
        return self._by_name.get(name)

    def names(self) -> list[str]:
        return list(self._by_name)

    def validate_intention(self, intention: Intention) -> None:
        cap = self._by_name.get(intention.capability)
        if cap is None:
            raise UnknownCapability(intention.capability)
        missing = [a for a in cap.required_args if a not in intention.args]
        if missing:
            raise MissingArgs(f"{intention.capability}: {missing}")
```

- [ ] **Step 4 : Implémenter le chargement de politique**

Créer `core/policy/loading.py` :

```python
"""Chargement et validation de la politique au démarrage.

Une politique invalide DOIT empêcher le démarrage plutôt que de dégrader en
silence : règle malformée (Pydantic) ou glob qui ne couvre aucune capacité
connue (typo de l'opérateur) → ``PolicyError``.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from pydantic import ValidationError

from core.policy.catalog import CapabilityCatalog
from core.policy.models import Rule


class PolicyError(Exception):
    """La politique fournie est invalide ; le serveur ne doit pas démarrer."""


def load_policy(raw_rules: list[dict[str, Any]], catalog: CapabilityCatalog) -> list[Rule]:
    rules: list[Rule] = []
    known = catalog.names()
    for i, raw in enumerate(raw_rules):
        try:
            rule = Rule.model_validate(raw)
        except ValidationError as exc:
            raise PolicyError(f"règle #{i} malformée : {exc}") from exc
        if not any(fnmatchcase(name, rule.match.capability) for name in known):
            raise PolicyError(
                f"règle #{i} : le glob '{rule.match.capability}' ne couvre aucune capacité connue"
            )
        rules.append(rule)
    return rules
```

- [ ] **Step 5 : Lancer les tests + portes qualité**

Run : `./.venv/bin/pytest tests/core/test_policy_loading.py -q && ./.venv/bin/ruff check core && ./.venv/bin/mypy core`
Expected : PASS partout.

- [ ] **Step 6 : Commit**

```bash
git add core/policy/catalog.py core/policy/loading.py tests/core/test_policy_loading.py
git commit -m "feat(core/policy): catalogue de capacites et chargement fail-closed de la politique"
```

---

### Task 3 : Tokenisation (`tokens/`)

**Files:**
- Create: `core/tokens/__init__.py`, `core/tokens/vault.py`
- Test: `tests/core/test_tokens.py`

**Interfaces:**
- Produces :
  - `ExtractFn = Callable[[str], dict[str, list[str]]]`
  - `class Vault` : `def token_for(label: str, value: str) -> str`, `def resolve(token: str) -> str | None`, `def values() -> set[str]`
  - `def tokenize(text: str, vault: Vault, extract: ExtractFn) -> str`
  - `def detokenize(obj: Any, vault: Vault) -> Any` (récursif : str / dict / list)

- [ ] **Step 1 : Écrire les tests (échec attendu)**

Créer `tests/core/test_tokens.py` :

```python
from core.tokens.vault import Vault, detokenize, tokenize


def _fake_extract(text: str) -> dict[str, list[str]]:
    # Extracteur déterministe de test — pas de spaCy.
    out: dict[str, list[str]] = {"IP": [], "VPN_USER": []}
    for tok in text.replace(",", " ").split():
        if tok.count(".") == 3 and tok.replace(".", "").isdigit():
            out["IP"].append(tok)
        elif tok.startswith("user:"):
            out["VPN_USER"].append(tok)
    return out


def test_tokenize_remplace_les_valeurs() -> None:
    v = Vault()
    out = tokenize("ban 10.0.0.5 et 10.0.0.6", v, _fake_extract)
    assert "10.0.0.5" not in out and "10.0.0.6" not in out
    assert "IP_1" in out and "IP_2" in out


def test_meme_valeur_meme_jeton_dans_la_session() -> None:
    v = Vault()
    out = tokenize("10.0.0.5 puis 10.0.0.5", v, _fake_extract)
    assert out.count("IP_1") == 2  # bijection stable dans la session


def test_round_trip() -> None:
    v = Vault()
    out = tokenize("ban 10.0.0.5", v, _fake_extract)
    assert detokenize(out, v) == "ban 10.0.0.5"


def test_detokenize_recursif_sur_struct() -> None:
    v = Vault()
    tokenize("10.0.0.5", v, _fake_extract)  # peuple le vault : IP_1 -> 10.0.0.5
    struct = {"cmd": "ban", "args": {"ip": "IP_1", "list": ["IP_1"]}}
    assert detokenize(struct, v) == {"cmd": "ban", "args": {"ip": "10.0.0.5", "list": ["10.0.0.5"]}}


def test_deux_sessions_sans_jeton_commun() -> None:
    v1, v2 = Vault(), Vault()
    tokenize("10.0.0.5", v1, _fake_extract)
    tokenize("10.0.0.9", v2, _fake_extract)
    # IP_1 de v1 et IP_1 de v2 designent des valeurs differentes -> pas de fuite inter-session
    assert v1.resolve("IP_1") == "10.0.0.5"
    assert v2.resolve("IP_1") == "10.0.0.9"


def test_property_aucune_valeur_du_vault_dans_le_texte_tokenise() -> None:
    v = Vault()
    out = tokenize("10.0.0.5 user:bob 10.0.0.6", v, _fake_extract)
    for real in v.values():
        assert real not in out
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run : `./.venv/bin/pytest tests/core/test_tokens.py -q`
Expected : FAIL — `ModuleNotFoundError: No module named 'core.tokens'`.

- [ ] **Step 3 : Implémenter le vault + tokenize/detokenize**

Créer `core/tokens/vault.py` :

```python
"""Tokenisation réversible des valeurs sensibles, liée à la session.

Le LLM et les logs ne voient QUE des jetons (``IP_1``, ``VPN_USER_2``). La table
jeton→valeur (le ``vault``) reste côté serveur et n'est jamais sérialisée hors de
celui-ci. La détokenisation n'a lieu qu'au tout dernier moment (cf. ``execution/``)
ou dans la vue d'approbation humaine.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

ExtractFn = Callable[[str], dict[str, list[str]]]


class Vault:
    """Bijection jeton↔valeur pour UNE session. Aucun état partagé entre sessions."""

    def __init__(self) -> None:
        self._to_real: dict[str, str] = {}
        self._to_token: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def token_for(self, label: str, value: str) -> str:
        existing = self._to_token.get(value)
        if existing is not None:
            return existing
        self._counters[label] = self._counters.get(label, 0) + 1
        token = f"{label}_{self._counters[label]}"
        self._to_real[token] = value
        self._to_token[value] = token
        return token

    def resolve(self, token: str) -> str | None:
        return self._to_real.get(token)

    def values(self) -> set[str]:
        return set(self._to_real.values())


def tokenize(text: str, vault: Vault, extract: ExtractFn) -> str:
    """Remplace chaque entité sensible détectée par son jeton stable de session."""
    entities = extract(text)
    # Remplacement par longueur décroissante : évite qu'une valeur sous-chaîne
    # d'une autre soit remplacée en premier.
    pairs: list[tuple[str, str]] = []
    for label, values in entities.items():
        for value in values:
            if value:
                pairs.append((label, value))
    for label, value in sorted(pairs, key=lambda p: len(p[1]), reverse=True):
        text = text.replace(value, vault.token_for(label, value))
    return text


def detokenize(obj: Any, vault: Vault) -> Any:
    """Remplace récursivement les jetons par leurs valeurs réelles (str/dict/list)."""
    if isinstance(obj, str):
        real = vault.resolve(obj)
        return real if real is not None else obj
    if isinstance(obj, dict):
        return {k: detokenize(v, vault) for k, v in obj.items()}
    if isinstance(obj, list):
        return [detokenize(v, vault) for v in obj]
    return obj
```

Créer `core/tokens/__init__.py` :

```python
from core.tokens.vault import ExtractFn, Vault, detokenize, tokenize

__all__ = ["ExtractFn", "Vault", "detokenize", "tokenize"]
```

- [ ] **Step 4 : Lancer les tests + portes qualité**

Run : `./.venv/bin/pytest tests/core/test_tokens.py -q && ./.venv/bin/ruff check core && ./.venv/bin/mypy core`
Expected : PASS partout.

- [ ] **Step 5 : Commit**

```bash
git add core/tokens tests/core/test_tokens.py
git commit -m "feat(core/tokens): tokenisation reversible par session (vault, tokenize/detokenize)"
```

---

### Task 4 : Authentification (`auth/`)

**Files:**
- Create: `core/auth/__init__.py`, `core/auth/api_key.py`
- Test: `tests/core/test_auth.py`

**Interfaces:**
- Produces :
  - `class AuthNotConfigured(Exception)`
  - `def load_auth_secret(env: Mapping[str, str], var: str = "COORDINATOR_API_KEY") -> str` (lève `AuthNotConfigured` si absent/vide)
  - `def verify(provided: str | None, expected: str) -> bool` (comparaison temps constant)
  - `def make_auth_dependency(expected: str) -> Callable[..., None]` (dépendance FastAPI ; lève `HTTPException(401)` si invalide)

- [ ] **Step 1 : Écrire les tests (échec attendu)**

Créer `tests/core/test_auth.py` :

```python
import pytest

from core.auth.api_key import AuthNotConfigured, load_auth_secret, verify


def test_load_secret_absent_leve() -> None:
    with pytest.raises(AuthNotConfigured):
        load_auth_secret({})


def test_load_secret_vide_leve() -> None:
    with pytest.raises(AuthNotConfigured):
        load_auth_secret({"COORDINATOR_API_KEY": ""})


def test_load_secret_present() -> None:
    assert load_auth_secret({"COORDINATOR_API_KEY": "s3cret"}) == "s3cret"


def test_verify() -> None:
    assert verify("s3cret", "s3cret") is True
    assert verify("wrong", "s3cret") is False
    assert verify(None, "s3cret") is False
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run : `./.venv/bin/pytest tests/core/test_auth.py -q`
Expected : FAIL — `ModuleNotFoundError: No module named 'core.auth'`.

- [ ] **Step 3 : Implémenter l'auth**

Créer `core/auth/api_key.py` :

```python
"""Authentification par clé API — fail-closed au démarrage, dépendance globale.

Le serveur DOIT refuser de démarrer sans secret configuré (``load_auth_secret``
lève). La vérification est en temps constant. La dépendance FastAPI est destinée
à être appliquée GLOBALEMENT (à toutes les routes), pour qu'on ne puisse pas
oublier de protéger une route neuve.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable, Mapping

from fastapi import Header, HTTPException, status


class AuthNotConfigured(Exception):
    """Aucun secret d'auth configuré — le serveur ne doit pas démarrer."""


def load_auth_secret(env: Mapping[str, str], var: str = "COORDINATOR_API_KEY") -> str:
    secret = env.get(var, "")
    if not secret:
        raise AuthNotConfigured(
            f"{var} absent ou vide : le coordinateur refuse de démarrer sans authentification"
        )
    return secret


def verify(provided: str | None, expected: str) -> bool:
    if provided is None:
        return False
    return hmac.compare_digest(provided, expected)


def make_auth_dependency(expected: str) -> Callable[[str | None], None]:
    """Fabrique la dépendance FastAPI liée au secret chargé au démarrage."""

    def _require(x_api_key: str | None = Header(default=None)) -> None:
        if not verify(x_api_key, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="clé API invalide ou absente")

    return _require
```

Créer `core/auth/__init__.py` :

```python
from core.auth.api_key import AuthNotConfigured, load_auth_secret, make_auth_dependency, verify

__all__ = ["AuthNotConfigured", "load_auth_secret", "make_auth_dependency", "verify"]
```

- [ ] **Step 4 : Ajouter le test d'invariant « toutes les routes authentifiées »**

Ce test protège l'invariant central : aucune route (sauf un allowlist explicite) ne doit échapper à la dépendance d'auth. Ajouter à `tests/core/test_auth.py` :

```python
def test_toutes_les_routes_portent_la_dependance_auth() -> None:
    from fastapi import Depends, FastAPI

    from core.auth.api_key import make_auth_dependency

    dep = make_auth_dependency("s3cret")
    app = FastAPI(dependencies=[Depends(dep)])  # dépendance GLOBALE

    @app.get("/api/status")
    def _status() -> dict[str, str]:
        return {"ok": "1"}

    # Introspection : chaque route applicative doit référencer la dépendance globale.
    from starlette.routing import Route

    app_routes = [r for r in app.routes if isinstance(r, Route) and r.path.startswith("/api")]
    assert app_routes, "au moins une route applicative"
    for route in app_routes:
        dep_calls = [d.call for d in route.dependant.dependencies]
        assert dep in dep_calls, f"route {route.path} sans dépendance d'auth"
```

- [ ] **Step 5 : Lancer les tests + portes qualité**

Run : `./.venv/bin/pytest tests/core/test_auth.py -q && ./.venv/bin/ruff check core && ./.venv/bin/mypy core`
Expected : PASS partout.

- [ ] **Step 6 : Commit**

```bash
git add core/auth tests/core/test_auth.py
git commit -m "feat(core/auth): cle API fail-closed, dependance globale, verif temps constant"
```

---

### Task 5 : Frontière d'exécution + `Authorized` infalsifiable (`execution/`)

**Files:**
- Create: `core/execution/__init__.py`, `core/execution/authorization.py`, `core/execution/boundary.py`
- Test: `tests/core/test_execution.py`

**Interfaces:**
- Consumes: `Verdict`, `Intention` (Task 1) ; `Vault`, `detokenize` (Task 3).
- Produces :
  - `class NotAuthorized(Exception)`
  - `class Authorized` (constructible UNIQUEMENT via `grant`/`grant_approved`)
  - `def grant(verdict: Verdict) -> Authorized` (lève `NotAuthorized` si `effect != "allow"`)
  - `AgentCall = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]`
  - `async def execute(authorization: Authorized, vault: Vault, call: AgentCall) -> dict[str, Any]`

- [ ] **Step 1 : Écrire les tests (échec attendu)**

Créer `tests/core/test_execution.py` :

```python
import pytest

from core.execution.authorization import Authorized, NotAuthorized, grant
from core.execution.boundary import execute
from core.policy.models import Intention, Rule, Verdict
from core.tokens.vault import Vault, tokenize


def _extract(text: str) -> dict[str, list[str]]:
    return {"IP": [t for t in text.split() if t.count(".") == 3]}


def _allow(intention: Intention) -> Verdict:
    return Verdict(effect="allow", matched_rule=Rule.model_validate(
        {"match": {"capability": intention.capability}, "effect": "allow"}), intention=intention)


def test_authorized_infalsifiable() -> None:
    it = Intention(capability="crowdsec.add_ban", args={})
    with pytest.raises(TypeError):
        Authorized(it, object())  # sentinelle bidon -> refus


def test_grant_refuse_un_verdict_non_allow() -> None:
    it = Intention(capability="crowdsec.add_ban", args={})
    deny = Verdict(effect="deny", matched_rule=None, intention=it)
    with pytest.raises(NotAuthorized):
        grant(deny)


def test_grant_produit_un_authorized_pour_allow() -> None:
    it = Intention(capability="crowdsec.get_decisions", args={})
    assert isinstance(grant(_allow(it)), Authorized)


async def test_execute_detokenise_avant_l_appel() -> None:
    v = Vault()
    tok = tokenize("10.0.0.5", v, _extract)  # IP_1 -> 10.0.0.5
    it = Intention(capability="crowdsec.add_ban", args={"ip": tok})
    seen: dict[str, dict[str, str]] = {}

    async def call(capability: str, args: dict[str, str]) -> dict[str, str]:
        seen["args"] = args
        return {"status": "ok"}

    result = await execute(grant(_allow(it)), v, call)
    assert result == {"status": "ok"}
    assert seen["args"] == {"ip": "10.0.0.5"}  # détokenisé au dernier moment
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run : `./.venv/bin/pytest tests/core/test_execution.py -q`
Expected : FAIL — `ModuleNotFoundError: No module named 'core.execution'`.

- [ ] **Step 3 : Implémenter `Authorized` + `grant`**

Créer `core/execution/authorization.py` :

```python
"""Preuve d'autorisation infalsifiable.

``execution.execute`` n'accepte QUE un ``Authorized``, que seuls ``grant`` (verdict
``allow``) ou ``grant_approved`` (approbation humaine résolue) peuvent produire.
Fabriquer un ``Authorized`` hors de ces fabriques est impossible (sentinelle privée)
— mypy et le runtime deviennent des gardiens de sécurité.
"""

from __future__ import annotations

from core.policy.models import Intention, Verdict

_GRANT = object()  # sentinelle privée au module


class NotAuthorized(Exception):
    """Tentative d'autoriser un verdict qui n'est pas ``allow``."""


class Authorized:
    """Intention prouvée autorisée. Ne peut être construite que par grant()/grant_approved()."""

    __slots__ = ("intention",)

    def __init__(self, intention: Intention, _grant: object) -> None:
        if _grant is not _GRANT:
            raise TypeError("Authorized ne peut être construit que par grant()/grant_approved()")
        self.intention = intention


def grant(verdict: Verdict) -> Authorized:
    if verdict.effect != "allow":
        raise NotAuthorized(verdict.effect)
    return Authorized(verdict.intention, _GRANT)


def _grant_intention(intention: Intention) -> Authorized:
    """Fabrique interne réservée au flux d'approbation (Task 7)."""
    return Authorized(intention, _GRANT)
```

- [ ] **Step 4 : Implémenter la frontière `execute`**

Créer `core/execution/boundary.py` :

```python
"""Frontière d'exécution : détokenise puis appelle l'agent-outil.

Seul endroit (avec la vue d'approbation humaine) où une valeur réelle réapparaît.
Prend un ``Authorized`` — pas une intention brute — donc rien n'atteint un
équipement sans être passé par la politique.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from core.execution.authorization import Authorized
from core.tokens.vault import Vault, detokenize

AgentCall = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]


async def execute(authorization: Authorized, vault: Vault, call: AgentCall) -> dict[str, Any]:
    real_args: dict[str, str] = detokenize(authorization.intention.args, vault)
    return await call(authorization.intention.capability, real_args)
```

Créer `core/execution/__init__.py` :

```python
from core.execution.authorization import Authorized, NotAuthorized, grant
from core.execution.boundary import AgentCall, execute

__all__ = ["AgentCall", "Authorized", "NotAuthorized", "execute", "grant"]
```

- [ ] **Step 5 : Lancer les tests + portes qualité**

Run : `./.venv/bin/pytest tests/core/test_execution.py -q && ./.venv/bin/ruff check core && ./.venv/bin/mypy core`
Expected : PASS partout.

- [ ] **Step 6 : Commit**

```bash
git add core/execution tests/core/test_execution.py
git commit -m "feat(core/execution): frontiere d execution et Authorized infalsifiable par les types"
```

---

### Task 6 : Journal d'audit (`audit/`)

**Files:**
- Create: `core/audit/__init__.py`, `core/audit/sink.py`
- Test: `tests/core/test_audit.py`

**Interfaces:**
- Consumes: `Verdict` (Task 1).
- Produces :
  - `class AuditEntry(BaseModel)` : `event: str`, `capability: str`, `effect: str`, `rule_reason: str | None`, `args: dict[str, str]`, `actor: str = "coordinator"`
  - `def entry_from_verdict(verdict: Verdict, event: str, actor: str = "coordinator") -> AuditEntry`
  - `class AuditSink(Protocol)` : `def write(entry: AuditEntry) -> None`
  - `class MemoryAuditSink(AuditSink)` : garde `entries: list[AuditEntry]` (pour tests/dev)

- [ ] **Step 1 : Écrire les tests (échec attendu)**

Créer `tests/core/test_audit.py` :

```python
from core.audit.sink import AuditEntry, MemoryAuditSink, entry_from_verdict
from core.policy.models import Intention, Verdict
from core.tokens.vault import Vault, tokenize


def _extract(text: str) -> dict[str, list[str]]:
    return {"IP": [t for t in text.split() if t.count(".") == 3]}


def test_entry_from_verdict_ne_porte_que_des_jetons() -> None:
    v = Vault()
    tok = tokenize("10.0.0.5", v, _extract)
    it = Intention(capability="crowdsec.add_ban", args={"ip": tok})
    verdict = Verdict(effect="deny", matched_rule=None, intention=it)
    entry = entry_from_verdict(verdict, event="policy_decision")
    assert entry.effect == "deny"
    assert entry.args == {"ip": "IP_1"}


def test_property_aucune_valeur_reelle_dans_l_audit() -> None:
    v = Vault()
    tok = tokenize("10.0.0.5", v, _extract)
    it = Intention(capability="crowdsec.add_ban", args={"ip": tok})
    sink = MemoryAuditSink()
    sink.write(entry_from_verdict(Verdict(effect="allow", matched_rule=None, intention=it), event="e"))
    serialized = "".join(e.model_dump_json() for e in sink.entries)
    for real in v.values():
        assert real not in serialized  # le vault ne fuite jamais dans l'audit
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run : `./.venv/bin/pytest tests/core/test_audit.py -q`
Expected : FAIL — `ModuleNotFoundError: No module named 'core.audit'`.

- [ ] **Step 3 : Implémenter le puits d'audit**

Créer `core/audit/sink.py` :

```python
"""Journal d'audit — append-only, JETONS uniquement.

L'audit reçoit des données déjà tokenisées (l'invariant est vérifié par test de
propriété) : aucune valeur réelle ne doit y apparaître. Le puits mémoire sert au
dev/tests ; un puits fichier/OpenSearch viendra en exploitation (sous-projet D).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from core.policy.models import Verdict


class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event: str
    capability: str
    effect: str
    rule_reason: str | None
    args: dict[str, str]
    actor: str = "coordinator"


def entry_from_verdict(verdict: Verdict, event: str, actor: str = "coordinator") -> AuditEntry:
    return AuditEntry(
        event=event,
        capability=verdict.intention.capability,
        effect=verdict.effect,
        rule_reason=(verdict.matched_rule.reason if verdict.matched_rule else None),
        args=verdict.intention.args,
        actor=actor,
    )


class AuditSink(Protocol):
    def write(self, entry: AuditEntry) -> None: ...


class MemoryAuditSink:
    """Puits en mémoire (dev/tests). Append-only."""

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def write(self, entry: AuditEntry) -> None:
        self.entries.append(entry)
```

Créer `core/audit/__init__.py` :

```python
from core.audit.sink import AuditEntry, AuditSink, MemoryAuditSink, entry_from_verdict

__all__ = ["AuditEntry", "AuditSink", "MemoryAuditSink", "entry_from_verdict"]
```

- [ ] **Step 4 : Lancer les tests + portes qualité**

Run : `./.venv/bin/pytest tests/core/test_audit.py -q && ./.venv/bin/ruff check core && ./.venv/bin/mypy core`
Expected : PASS partout.

- [ ] **Step 5 : Commit**

```bash
git add core/audit tests/core/test_audit.py
git commit -m "feat(core/audit): puits d audit append-only jetons-seulement"
```

---

### Task 7 : Flux d'approbation humaine (`approval/`)

**Files:**
- Create: `core/approval/__init__.py`, `core/approval/store.py`
- Modify: `core/execution/authorization.py` (ajouter `grant_approved`)
- Test: `tests/core/test_approval.py`

**Interfaces:**
- Consumes: `Intention` (Task 1), `Authorized`, `_grant_intention` (Task 5).
- Produces :
  - `def intention_hash(intention: Intention) -> str` (sha256 du JSON canonique)
  - `State = Literal["pending", "approved", "rejected", "expired"]`
  - `class Approval(BaseModel)` : `id: str`, `intention: Intention`, `intention_hash: str`, `state: State`
  - `class ApprovalMismatch(Exception)`
  - `class ApprovalStore` : `def create(intention) -> Approval`, `def approve(approval_id: str, provided_hash: str) -> Approval`, `def reject(approval_id: str) -> Approval`, `def get(approval_id) -> Approval | None`
  - `def grant_approved(approval: Approval) -> Authorized` (lève si `state != "approved"`)

- [ ] **Step 1 : Écrire les tests (échec attendu)**

Créer `tests/core/test_approval.py` :

```python
import pytest

from core.approval.store import (
    Approval,
    ApprovalMismatch,
    ApprovalStore,
    intention_hash,
)
from core.execution.authorization import Authorized, NotAuthorized, grant_approved
from core.policy.models import Intention


def _it(cap: str = "opnsense.add_nat", **args: str) -> Intention:
    return Intention(capability=cap, args=dict(args))


def test_hash_stable_et_sensible() -> None:
    a, b = _it(interface="wan"), _it(interface="wan")
    assert intention_hash(a) == intention_hash(b)
    assert intention_hash(a) != intention_hash(_it(interface="lan"))


def test_creation_est_pending() -> None:
    ap = ApprovalStore().create(_it())
    assert ap.state == "pending"


def test_approve_lie_au_hash_exact() -> None:
    store = ApprovalStore()
    ap = store.create(_it(interface="wan"))
    with pytest.raises(ApprovalMismatch):
        store.approve(ap.id, "hash_qui_ne_correspond_pas")
    ok = store.approve(ap.id, ap.intention_hash)
    assert ok.state == "approved"


def test_grant_approved_seulement_si_approuve() -> None:
    store = ApprovalStore()
    ap = store.create(_it())
    with pytest.raises(NotAuthorized):
        grant_approved(ap)  # encore pending
    approved = store.approve(ap.id, ap.intention_hash)
    assert isinstance(grant_approved(approved), Authorized)


def test_reject_bloque_l_autorisation() -> None:
    store = ApprovalStore()
    ap = store.reject(store.create(_it()).id)
    assert ap.state == "rejected"
    with pytest.raises(NotAuthorized):
        grant_approved(ap)
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run : `./.venv/bin/pytest tests/core/test_approval.py -q`
Expected : FAIL — `ModuleNotFoundError: No module named 'core.approval'`.

- [ ] **Step 3 : Implémenter le store d'approbation**

Créer `core/approval/store.py` :

```python
"""Approbation humaine — fail-closed, liaison exacte intention↔autorisation.

Une approbation jamais résolue n'autorise rien (défaut pending → jamais exécuté).
Approuver produit une autorisation liée au HASH de l'intention précise montrée :
approuver X puis présenter X′ ≠ X échoue (contre la substitution de directive).
L'``id`` est fourni par l'appelant (pas d'horloge/aléa ici, pour garder ce module
pur et déterministe ; l'unicité est garantie par le serveur en amont).
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict

from core.policy.models import Intention

State = Literal["pending", "approved", "rejected", "expired"]


class ApprovalMismatch(Exception):
    """Le hash fourni ne correspond pas à l'intention approuvée."""


class ApprovalNotFound(Exception):
    """Approbation inconnue."""


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    intention: Intention
    intention_hash: str
    state: State = "pending"


def intention_hash(intention: Intention) -> str:
    canonical = intention.model_dump_json()  # Pydantic ordonne les clés de façon stable
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalStore:
    """Registre des approbations en attente. Un seul thread (asyncio coopératif)."""

    def __init__(self) -> None:
        self._by_id: dict[str, Approval] = {}
        self._seq = 0

    def create(self, intention: Intention, approval_id: str | None = None) -> Approval:
        if approval_id is None:
            self._seq += 1
            approval_id = f"appr-{self._seq}"
        ap = Approval(id=approval_id, intention=intention, intention_hash=intention_hash(intention))
        self._by_id[approval_id] = ap
        return ap

    def get(self, approval_id: str) -> Approval | None:
        return self._by_id.get(approval_id)

    def approve(self, approval_id: str, provided_hash: str) -> Approval:
        ap = self._require(approval_id)
        if provided_hash != ap.intention_hash:
            raise ApprovalMismatch(approval_id)
        updated = ap.model_copy(update={"state": "approved"})
        self._by_id[approval_id] = updated
        return updated

    def reject(self, approval_id: str) -> Approval:
        ap = self._require(approval_id)
        updated = ap.model_copy(update={"state": "rejected"})
        self._by_id[approval_id] = updated
        return updated

    def _require(self, approval_id: str) -> Approval:
        ap = self._by_id.get(approval_id)
        if ap is None:
            raise ApprovalNotFound(approval_id)
        return ap
```

Créer `core/approval/__init__.py` :

```python
from core.approval.store import (
    Approval,
    ApprovalMismatch,
    ApprovalNotFound,
    ApprovalStore,
    State,
    intention_hash,
)

__all__ = [
    "Approval",
    "ApprovalMismatch",
    "ApprovalNotFound",
    "ApprovalStore",
    "State",
    "intention_hash",
]
```

- [ ] **Step 4 : Ajouter `grant_approved` à `core/execution/authorization.py`**

Ajouter l'import et la fabrique (elle réutilise la sentinelle privée du module) :

```python
from core.approval.store import Approval  # en tête du fichier
```

et à la fin :

```python
def grant_approved(approval: Approval) -> Authorized:
    if approval.state != "approved":
        raise NotAuthorized(f"approbation {approval.id} en état {approval.state}")
    return _grant_intention(approval.intention)
```

Puis exposer `grant_approved` dans `core/execution/__init__.py` :

```python
from core.execution.authorization import Authorized, NotAuthorized, grant, grant_approved

__all__ = ["AgentCall", "Authorized", "NotAuthorized", "execute", "grant", "grant_approved"]
```

**Note import** : `core.execution.authorization` importe `core.approval.store`, qui importe `core.policy.models`. `core.approval` n'importe PAS `core.execution` → pas de cycle.

- [ ] **Step 5 : Lancer les tests + portes qualité**

Run : `./.venv/bin/pytest -q && ./.venv/bin/ruff check core && ./.venv/bin/mypy core`
Expected : PASS partout (suite complète — on a modifié `execution/`).

- [ ] **Step 6 : Commit**

```bash
git add core/approval core/execution tests/core/test_approval.py
git commit -m "feat(core/approval): approbation humaine fail-closed liee au hash de l intention"
```

---

### Task 8 : Orchestrateur de confiance (le cœur mince)

**Files:**
- Create: `core/orchestrator.py`
- Test: `tests/core/test_orchestrator.py`

**Interfaces:**
- Consumes: tout `core/*`.
- Produces :
  - `class Proposer(Protocol)` : `async def propose(prompt_tokenise: str) -> Intention`
  - `class Outcome(BaseModel)` : `status: Literal["executed", "denied", "pending_approval"]`, `verdict: Verdict`, `approval_id: str | None = None`, `result: dict[str, Any] | None = None`
  - `class TrustOrchestrator` : `__init__(policy, catalog, extract, proposer, call, sink, approvals)` ; `async def handle(request_text: str) -> Outcome` ; `async def resume(approval_id: str) -> Outcome`

- [ ] **Step 1 : Écrire le test d'intégration (échec attendu)**

Créer `tests/core/test_orchestrator.py` :

```python
from typing import Any

from core.approval.store import ApprovalStore
from core.audit.sink import MemoryAuditSink
from core.orchestrator import TrustOrchestrator
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import ArgMatch, Intention, Match, Rule


def _extract(text: str) -> dict[str, list[str]]:
    return {"IP": [t for t in text.replace(",", " ").split() if t.count(".") == 3]}


def _catalog() -> CapabilityCatalog:
    return CapabilityCatalog([
        Capability(name="crowdsec.add_ban", required_args=["ip"]),
        Capability(name="opnsense.add_nat", required_args=["interface"]),
    ])


class _Proposer:
    """Faux LLM : renvoie une intention scriptée (déjà tokenisée par l'orchestrateur)."""

    def __init__(self, intention: Intention) -> None:
        self._it = intention

    async def propose(self, prompt: str) -> Intention:
        # Vérifie au passage que le prompt est tokenisé (aucune IP réelle).
        assert "10.0.0.5" not in prompt
        return self._it


def _calls() -> tuple[list[dict[str, str]], Any]:
    seen: list[dict[str, str]] = []

    async def call(capability: str, args: dict[str, str]) -> dict[str, str]:
        seen.append({"capability": capability, **args})
        return {"status": "ok"}

    return seen, call


async def test_allow_execute_et_detokenise() -> None:
    seen, call = _calls()
    sink = MemoryAuditSink()
    policy = [Rule(match=Match(capability="crowdsec.add_ban"), effect="allow")]
    orch = TrustOrchestrator(
        policy=policy, catalog=_catalog(), extract=_extract,
        proposer=_Proposer(Intention(capability="crowdsec.add_ban", args={"ip": "IP_1"})),
        call=call, sink=sink, approvals=ApprovalStore(),
    )
    out = await orch.handle("bannir 10.0.0.5")
    assert out.status == "executed"
    assert seen == [{"capability": "crowdsec.add_ban", "ip": "10.0.0.5"}]
    # L'audit ne porte que des jetons.
    assert all("10.0.0.5" not in e.model_dump_json() for e in sink.entries)


async def test_deny_n_execute_rien() -> None:
    seen, call = _calls()
    orch = TrustOrchestrator(
        policy=[], catalog=_catalog(), extract=_extract,
        proposer=_Proposer(Intention(capability="crowdsec.add_ban", args={"ip": "IP_1"})),
        call=call, sink=MemoryAuditSink(), approvals=ApprovalStore(),
    )
    out = await orch.handle("bannir 10.0.0.5")
    assert out.status == "denied" and seen == []


async def test_approve_suspend_puis_resume_execute() -> None:
    seen, call = _calls()
    policy = [Rule(match=Match(capability="opnsense.add_nat"), effect="approve")]
    approvals = ApprovalStore()
    orch = TrustOrchestrator(
        policy=policy, catalog=_catalog(), extract=_extract,
        proposer=_Proposer(Intention(capability="opnsense.add_nat", args={"interface": "lan"})),
        call=call, sink=MemoryAuditSink(), approvals=approvals,
    )
    out = await orch.handle("ajouter un nat")
    assert out.status == "pending_approval" and out.approval_id is not None
    assert seen == []  # rien exécuté tant que non approuvé
    ap = approvals.get(out.approval_id)
    assert ap is not None
    approvals.approve(ap.id, ap.intention_hash)
    resumed = await orch.resume(out.approval_id)
    assert resumed.status == "executed" and len(seen) == 1
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run : `./.venv/bin/pytest tests/core/test_orchestrator.py -q`
Expected : FAIL — `ModuleNotFoundError: No module named 'core.orchestrator'`.

- [ ] **Step 3 : Implémenter l'orchestrateur**

Créer `core/orchestrator.py` :

```python
"""Orchestrateur de confiance — le cœur mince qui compose les feuilles pures.

Flux : requête → tokenize → le LLM PROPOSE une intention → validation catalogue →
evaluate → { deny: stop | approve: suspend | allow: grant+execute } → audit.
Aucune valeur réelle ne quitte cette frontière vers le LLM ou l'audit ; seul
``execution.execute`` détokenise, au dernier moment.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from core.approval.store import ApprovalStore
from core.audit.sink import AuditSink, entry_from_verdict
from core.execution.authorization import grant, grant_approved
from core.execution.boundary import AgentCall, execute
from core.policy.catalog import CapabilityCatalog
from core.policy.engine import evaluate
from core.policy.models import Intention, Rule, Verdict
from core.tokens.vault import ExtractFn, Vault, tokenize

Status = Literal["executed", "denied", "pending_approval"]


class Proposer(Protocol):
    async def propose(self, prompt_tokenise: str) -> Intention: ...


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status
    verdict: Verdict
    approval_id: str | None = None
    result: dict[str, Any] | None = None


class TrustOrchestrator:
    def __init__(
        self,
        *,
        policy: list[Rule],
        catalog: CapabilityCatalog,
        extract: ExtractFn,
        proposer: Proposer,
        call: AgentCall,
        sink: AuditSink,
        approvals: ApprovalStore,
    ) -> None:
        self._policy = policy
        self._catalog = catalog
        self._extract = extract
        self._proposer = proposer
        self._call = call
        self._sink = sink
        self._approvals = approvals
        # Un vault par session d'approbation en attente, pour détokeniser au resume.
        self._vaults: dict[str, Vault] = {}

    async def handle(self, request_text: str) -> Outcome:
        vault = Vault()
        prompt = tokenize(request_text, vault, self._extract)
        intention = await self._proposer.propose(prompt)
        self._catalog.validate_intention(intention)  # lève si capacité inconnue / args manquants
        verdict = evaluate(intention, self._policy)
        self._sink.write(entry_from_verdict(verdict, event="policy_decision"))

        if verdict.effect == "deny":
            return Outcome(status="denied", verdict=verdict)
        if verdict.effect == "approve":
            approval = self._approvals.create(intention)
            self._vaults[approval.id] = vault
            return Outcome(status="pending_approval", verdict=verdict, approval_id=approval.id)

        result = await execute(grant(verdict), vault, self._call)
        self._sink.write(entry_from_verdict(verdict, event="executed"))
        return Outcome(status="executed", verdict=verdict, result=result)

    async def resume(self, approval_id: str) -> Outcome:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise KeyError(approval_id)
        vault = self._vaults.get(approval_id, Vault())
        verdict = Verdict(effect="approve", matched_rule=None, intention=approval.intention)
        # grant_approved lève si l'approbation n'est pas dans l'état "approved" (fail-closed).
        authorized = grant_approved(approval)
        result = await execute(authorized, vault, self._call)
        self._sink.write(entry_from_verdict(verdict, event="executed_after_approval"))
        self._vaults.pop(approval_id, None)
        return Outcome(status="executed", verdict=verdict, result=result)


__all__ = ["Outcome", "Proposer", "Status", "TrustOrchestrator"]
```

- [ ] **Step 4 : Lancer la suite complète + portes qualité**

Run : `./.venv/bin/pytest -q && ./.venv/bin/ruff check core && ./.venv/bin/mypy core`
Expected : PASS partout.

- [ ] **Step 5 : Commit**

```bash
git add core/orchestrator.py tests/core/test_orchestrator.py
git commit -m "feat(core): orchestrateur de confiance (tokenize -> propose -> policy -> approve/execute -> audit)"
```

---

### Task 9 : Mesure CQI et clôture de A

**Files:**
- Aucun fichier de code — vérification et documentation.

**Interfaces:**
- Consumes: tout `core/`.

- [ ] **Step 1 : Passe qualité complète**

Run : `./.venv/bin/ruff check . && ./.venv/bin/mypy core && ./.venv/bin/pytest -q --cov=core`
Expected : ruff (core) propre, mypy « Success », tous les tests verts, couverture `core/` élevée (viser ≥ 95 % sur les modules purs).

- [ ] **Step 2 : Audit CQI ciblé sur `core/`**

Lancer la compétence `cli-audit-code` sur `core/`. **Objectif : CQI > 9.** Consigner
le score obtenu. Si < 9, traiter les findings Critiques/Importants avant de clore
(chaque correction reste test-first).

- [ ] **Step 3 : Journaliser le résultat**

Ajouter une entrée datée à `docs/audit-2026-07.md` (section « Suivi ») : score CQI de
`core/`, ce que le sous-projet A a livré, et le rappel que le `coordinator/` legacy
(ReAct/Judge fail-open) n'est PAS encore débranché — c'est l'objet du câblage final,
hors de ce plan (il dépend de B, le contrat CAP v2).

- [ ] **Step 4 : Commit**

```bash
git add docs/audit-2026-07.md
git commit -m "docs: cloture du sous-projet A (coeur de confiance), score CQI de core/"
```

---

## Notes de fin (hors tasks)

- **Le `coordinator/` legacy n'est pas débranché par ce plan.** A construit le
  cœur de confiance en parallèle, sous `core/`, entièrement testé. Le remplacement
  du chemin de décision du coordinateur (retrait de ReAct/Judge fail-open, câblage
  sur `TrustOrchestrator`) dépend du contrat **CAP v2 (sous-projet B)** — c'est le
  premier travail de B.
- **Le catalogue de capacités** est ici un objet construit en mémoire. Sa
  dérivation depuis les `GET /capabilities` des agents, figée au démarrage, est un
  point de jonction avec **B**.
- **Reste hors A** : portabilité modèles/GPU (**C**), licence + packaging + puits
  d'audit persistant + isolation multi-tenant (**D**).
