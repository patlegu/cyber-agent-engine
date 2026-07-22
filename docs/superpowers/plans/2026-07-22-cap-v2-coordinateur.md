# CAP v2 & bascule du coordinateur — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Durcir le contrat structuré coordinateur↔agent (CAP v2), basculer le coordinateur du chemin ReAct/Judge *fail-open* legacy vers le cœur de confiance `core/`, et migrer l'agent CrowdSec de bout en bout — sans SLM sur le chemin d'exécution.

**Architecture :** Le LLM *propose* (JSON parsé/validé en `core.Intention`), `core/` *décide* (politique fail-closed) et *exécute* (frontière détokenisante + autorisation infalsifiable), l'agent *exécute structurellement* (`execute_direct` → `_call_function`, jamais `_infer_with_ollama`). Une boucle ReAct gatée orchestre les pas ; un verdict `approve` suspend la session (persistée, chiffrée, à échéance) jusqu'à reprise humaine.

**Tech Stack :** Python 3.11, Pydantic v2, FastAPI, httpx (UDS), pytest/pytest-asyncio, cryptography (Fernet), PyYAML. mypy strict, ruff.

## Global Constraints

- **CQI > 9 dès le départ, jamais en rétrofit.** Test-first à chaque tâche.
- **Fail-closed partout** : secret d'auth absent → refus de démarrer ; capacité inconnue → deny ; requête malformée → `success=False` ; approbation non résolue → rien exécuté.
- **Le LLM ne voit que des jetons.** Aucune valeur réelle (PII) dans les prompts, l'audit ou les logs. Seul `core.execution.execute` détokenise, au dernier moment.
- **Args du contrat = `dict[str, str]`** (la chaîne est string de bout en bout) ; la coercition vers les types déclarés se fait côté agent.
- **DRY** : CAP v2 = durcissement d'`agents/contracts.py`, **aucun** contrat parallèle. Réutiliser `execute_structured`/`execute_direct`/`_call_function` existants.
- **Aucun chemin legacy laissé « au cas où »** : ce qui est remplacé est supprimé dans le même commit que son remplaçant.
- **Injection de dépendances derrière Protocol** pour toute I/O (LLM, client agent, stores, horloge). Tests avec doubles déterministes — aucun réseau, aucune horloge implicite (pas de `Date.now()`/`time.time()` en dur dans la logique testée).
- **Commits** : style `type(scope): sujet` en minuscules, sans emoji, **sans** `Co-Authored-By`, **sans** mention d'IA/Claude/GPT (cf. AGENTS.md).
- **Docstrings en français**, substantielles, comme le reste du dépôt.
- mypy strict sur chaque nouveau module (vérifié par `mypy <module>` dans l'étape de test) ; ruff propre.

---

### Task 1 : Durcir le contrat CAP v2 (`agents/contracts.py`)

**Files:**
- Modify: `agents/contracts.py`
- Test: `tests/agents/test_contracts_cap_v2.py`
- Create: `tests/agents/__init__.py` (si absent)

**Interfaces:**
- Consumes: `agents/errors.py::ErrorCode` (existant).
- Produces:
  - `AgentExecuteRequest(BaseModel)` — `model_config = ConfigDict(extra="forbid")` ; `command: str | None = None` ; `function: str | None = None` ; `args: dict[str, str] = {}` ; validateurs : au moins un de `command`/`function` ; en mode structuré (`function` présent) : `len(function) <= 128`, `len(args) <= 64`, chaque clé `<= 128` et chaque valeur `<= 8192` caractères, sinon `ValueError`.
  - `AgentExecuteResponse(BaseModel)` — inchangé fonctionnellement mais `args: dict[str, str] = {}` et `model_config = ConfigDict(extra="forbid")`.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/agents/test_contracts_cap_v2.py
import pytest
from pydantic import ValidationError
from agents.contracts import AgentExecuteRequest


def test_structured_request_roundtrip():
    req = AgentExecuteRequest(function="ban_ip", args={"ip": "203.0.113.9"})
    assert req.function == "ban_ip"
    assert req.args == {"ip": "203.0.113.9"}


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        AgentExecuteRequest(function="ban_ip", args={}, entities={"IP": ["x"]})


def test_requires_command_or_function():
    with pytest.raises(ValidationError):
        AgentExecuteRequest(args={"ip": "x"})


def test_args_value_bound_rejected():
    with pytest.raises(ValidationError):
        AgentExecuteRequest(function="ban_ip", args={"ip": "x" * 8193})


def test_too_many_args_rejected():
    big = {f"k{i}": "v" for i in range(65)}
    with pytest.raises(ValidationError):
        AgentExecuteRequest(function="f", args=big)
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `.venv/bin/pytest tests/agents/test_contracts_cap_v2.py -q`
Expected: FAIL (`test_extra_field_forbidden`/`test_args_value_bound_rejected` passent l'instanciation alors qu'ils devraient lever).

- [ ] **Step 3 : Durcir `agents/contracts.py`**

Remplacer la classe `AgentExecuteRequest` et ajuster `AgentExecuteResponse` :

```python
from pydantic import BaseModel, ConfigDict, Field, model_validator

_MAX_ARGS = 64
_MAX_KEY_LEN = 128
_MAX_VAL_LEN = 8192
_MAX_FUNCTION_LEN = 128


class AgentExecuteRequest(BaseModel):
    """Requête d'exécution CAP v2. Mode structuré (`function`+`args`) sur la chaîne
    de confiance ; `command` (langage naturel) réservé au debug hors chaîne.
    """

    model_config = ConfigDict(extra="forbid")

    command: str | None = Field(default=None, description="Commande NL (mode debug).")
    function: str | None = Field(default=None, description="Fonction à appeler (mode structuré).")
    args: dict[str, str] = Field(default_factory=dict, description="Args structurés (str).")

    @model_validator(mode="after")
    def _validate(self) -> "AgentExecuteRequest":
        if not self.command and not self.function:
            raise ValueError("Either 'command' or 'function' must be provided.")
        if self.function is not None and len(self.function) > _MAX_FUNCTION_LEN:
            raise ValueError("function name too long")
        if len(self.args) > _MAX_ARGS:
            raise ValueError("too many args")
        for k, v in self.args.items():
            if len(k) > _MAX_KEY_LEN or len(v) > _MAX_VAL_LEN:
                raise ValueError(f"arg '{k}' exceeds size bound")
        return self
```

Pour `AgentExecuteResponse` : ajouter `model_config = ConfigDict(extra="forbid")` et changer `args: dict[str, Any]` → `args: dict[str, str] = Field(default_factory=dict)`. Garder `result: Any` (les résultats métier restent libres) et les helpers `is_retryable`/`is_missing_arg`/`is_permission_denied`.

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/agents/test_contracts_cap_v2.py -q && .venv/bin/mypy agents/contracts.py`
Expected: PASS ; mypy: Success.

- [ ] **Step 5 : Commit**

```bash
git add agents/contracts.py tests/agents/
git commit -m "feat(agents/contracts): durcir le contrat CAP v2 (extra=forbid, args str bornes)"
```

---

### Task 2 : Coercition string→type (`agents/coercion.py`)

**Files:**
- Create: `agents/coercion.py`
- Test: `tests/agents/test_coercion.py`

**Interfaces:**
- Produces:
  - `class CoercionError(Exception)` — valeur non convertible vers le type déclaré.
  - `def coerce_args(func: Callable[..., Any], args: dict[str, str]) -> dict[str, Any]` — pour chaque arg présent dans `args`, convertit sa valeur string vers le type annoté du paramètre de `func` : `int` → `int(v)` ; `bool` → `{"true","1"}→True / {"false","0"}→False` (insensible à la casse) ; `Literal[...]` → `v` doit ∈ valeurs littérales ; tout autre (`str`, non annoté) → `v` inchangé. `Optional[X]` déballé vers `X`. Valeur non convertible → `CoercionError`. Idempotent si la valeur est déjà du bon type.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/agents/test_coercion.py
from typing import Literal, Optional
import pytest
from agents.coercion import coerce_args, CoercionError


async def _f(decision_id: int, force: bool = False,
             scope: Literal["ip", "range"] = "ip",
             ip: str = "", limit: Optional[int] = None):
    ...


def test_coerces_declared_types():
    out = coerce_args(_f, {"decision_id": "123", "force": "true",
                           "scope": "range", "ip": "203.0.113.9", "limit": "50"})
    assert out == {"decision_id": 123, "force": True, "scope": "range",
                   "ip": "203.0.113.9", "limit": 50}


def test_bad_int_rejected():
    with pytest.raises(CoercionError):
        coerce_args(_f, {"decision_id": "abc"})


def test_literal_out_of_domain_rejected():
    with pytest.raises(CoercionError):
        coerce_args(_f, {"decision_id": "1", "scope": "country"})


def test_unknown_arg_passthrough():
    # arg non déclaré par func : laissé tel quel (le dispatch le rejettera si besoin)
    assert coerce_args(_f, {"decision_id": "1", "extra": "x"})["extra"] == "x"
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `.venv/bin/pytest tests/agents/test_coercion.py -q`
Expected: FAIL (`No module named 'agents.coercion'`).

- [ ] **Step 3 : Implémenter `agents/coercion.py`**

```python
"""Coercition des arguments string CAP v2 vers les types déclarés par la fonction.

Les args CAP v2 sont toujours des strings (chaîne de confiance string de bout en
bout). Certaines fonctions attendent `int`/`bool`/`Literal`. On convertit selon la
signature, AVANT le dispatch, et on rejette proprement toute valeur non convertible
plutôt que de laisser crasher l'appel réel.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from typing import Any


class CoercionError(Exception):
    """Une valeur string ne peut pas être convertie vers le type déclaré."""


_TRUE = {"true", "1"}
_FALSE = {"false", "0"}


def _unwrap_optional(ann: Any) -> Any:
    if typing.get_origin(ann) in (typing.Union, __import__("types").UnionType):
        non_none = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return ann


def _coerce_one(name: str, value: str, ann: Any) -> Any:
    ann = _unwrap_optional(ann)
    if typing.get_origin(ann) is typing.Literal:
        allowed = [str(v) for v in typing.get_args(ann)]
        if value not in allowed:
            raise CoercionError(f"{name}={value!r} hors domaine {allowed}")
        return value
    if ann is int:
        try:
            return int(value)
        except ValueError as exc:
            raise CoercionError(f"{name}={value!r} n'est pas un entier") from exc
    if ann is bool:
        low = value.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise CoercionError(f"{name}={value!r} n'est pas un booléen")
    return value


def coerce_args(func: Callable[..., Any], args: dict[str, str]) -> dict[str, Any]:
    """Convertit `args` selon les annotations de `func`. Args non déclarés : inchangés."""
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return dict(args)
    hints = typing.get_type_hints(func)
    out: dict[str, Any] = {}
    for key, value in args.items():
        param = sig.parameters.get(key)
        if param is None:
            out[key] = value
            continue
        ann = hints.get(key, param.annotation)
        if ann is inspect.Parameter.empty:
            out[key] = value
        else:
            out[key] = _coerce_one(key, value, ann)
    return out
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/agents/test_coercion.py -q && .venv/bin/mypy agents/coercion.py`
Expected: PASS ; mypy: Success.

- [ ] **Step 5 : Commit**

```bash
git add agents/coercion.py tests/agents/test_coercion.py
git commit -m "feat(agents/coercion): coercition string vers types declares avant dispatch"
```

---

### Task 3 : Câbler la coercition + fail-closed dans le chemin structuré de l'agent

**Files:**
- Modify: `agents/base.py` (`execute_direct`)
- Modify: `server.py` (retirer la branche CAP v1 ; auth fail-closed ; bornes)
- Test: `tests/agents/test_execute_direct_coercion.py`
- Test: `tests/agents/test_agent_server_structured.py`

**Interfaces:**
- Consumes: `agents.coercion.coerce_args`, `agents.coercion.CoercionError`, `agents/base.py::ToolAgent.execute_direct`, `core.auth.make_auth_dependency`, `core.auth.load_auth_secret`.
- Produces: `ToolAgent.execute_direct` coerce les args avant `_call_function` ; le serveur d'agent applique `core.auth` fail-closed et n'expose plus la branche CAP v1.

- [ ] **Step 1 : Écrire le test qui échoue (coercition dans execute_direct)**

```python
# tests/agents/test_execute_direct_coercion.py
import pytest
from typing import Dict
from agents.base import ToolAgent


class _FakeAgent(ToolAgent):
    def __init__(self):
        super().__init__(tool_name="fake", model_path=None)

    def _register_functions(self):
        return {"del_dec": self._del_dec}

    async def _del_dec(self, decision_id: int) -> Dict:
        return {"deleted": decision_id, "type": type(decision_id).__name__}


@pytest.mark.asyncio
async def test_execute_direct_coerces_int():
    agent = _FakeAgent()
    res = await agent.execute_direct("del_dec", {"decision_id": "42"})
    assert res.success is True
    assert res.result == {"deleted": 42, "type": "int"}


@pytest.mark.asyncio
async def test_execute_direct_bad_coercion_fails_closed():
    agent = _FakeAgent()
    res = await agent.execute_direct("del_dec", {"decision_id": "abc"})
    assert res.success is False
    assert res.error_code is not None
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `.venv/bin/pytest tests/agents/test_execute_direct_coercion.py -q`
Expected: FAIL (`del_dec` reçoit `"42"` string → `res.result["type"] == "str"`).

- [ ] **Step 3 : Coercer dans `execute_direct`**

Dans `agents/base.py`, au début de `execute_direct`, après avoir construit `start_time`, insérer la coercition si la fonction est connue :

```python
async def execute_direct(self, function: str, args: Dict[str, Any]) -> ToolResult:
    import time
    from .coercion import coerce_args, CoercionError
    start_time = time.time()
    func = self._functions.get(function)
    if func is not None:
        try:
            args = coerce_args(func, args)
        except CoercionError as exc:
            return ToolResult(
                success=False, function=function, args=args, result=None,
                error=str(exc), error_code=ErrorCode.MISSING_ARG,
                tool_name=self.tool_name,
                execution_time_ms=(time.time() - start_time) * 1000,
            )
    function_call = FunctionCall(
        function=function, args=args, confidence=1.0,
        reasoning="[direct call — no LLM inference]",
    )
    try:
        return await self._call_function(function_call, start_time)
    except Exception as e:
        import time as _t
        logger.error(f"Erreur execute_direct({function}): {e}")
        return ToolResult(
            success=False, function=function, args=args, result=None,
            error=str(e), error_code=self._classify_exception(e),
            tool_name=self.tool_name,
            execution_time_ms=(_t.time() - start_time) * 1000,
        )
```

- [ ] **Step 4 : Lancer le test, vérifier le succès**

Run: `.venv/bin/pytest tests/agents/test_execute_direct_coercion.py -q`
Expected: PASS.

- [ ] **Step 5 : Écrire le test du serveur d'agent (fail-closed + plus de CAP v1)**

```python
# tests/agents/test_agent_server_structured.py
import importlib
import pytest
from fastapi.testclient import TestClient


def _client(monkeypatch, key="secret"):
    monkeypatch.setenv("AGENT_API_KEY", key)
    import server
    importlib.reload(server)
    return TestClient(server.app)


def test_no_key_configured_refuses_start(monkeypatch):
    monkeypatch.delenv("AGENT_API_KEY", raising=False)
    import server
    with pytest.raises(Exception):
        importlib.reload(server)  # load_auth_secret lève AuthNotConfigured


def test_structured_requires_auth(monkeypatch):
    client = _client(monkeypatch)
    r = client.post("/agent/execute", json={"function": "get_metrics", "args": {}})
    assert r.status_code == 401


def test_cap_v1_directive_no_longer_dispatched(monkeypatch):
    client = _client(monkeypatch)
    # Un ancien paquet CAP v1 (command JSON avec entities) ne doit PAS être exécuté
    # structurellement : plus de fusion entities→args.
    r = client.post(
        "/agent/execute",
        headers={"X-API-Key": "secret"},
        json={"command": '{"directive": "ban_ip", "entities": {"IP_ADDRESS": ["203.0.113.9"]}, "args": {}}'},
    )
    # Soit 400 (aucun agent NL ne l'interprète en test), soit succès NL — mais
    # jamais un ban structuré silencieux depuis les entities.
    assert "203.0.113.9" not in r.text or r.json().get("function") != "ban_ip"
```

- [ ] **Step 6 : Durcir `server.py` (auth fail-closed, suppression CAP v1)**

Dans `server.py` :
1. Remplacer `verify_api_key` fail-open par la dépendance `core.auth` :

```python
from core.auth.api_key import load_auth_secret, make_auth_dependency

_AGENT_SECRET = load_auth_secret(os.environ, "AGENT_API_KEY")  # lève si absent → refus de démarrer
verify_api_key = make_auth_dependency(_AGENT_SECRET)
```

Adapter les décorateurs de routes : `dependencies=[Depends(verify_api_key)]` reste valide (la fabrique renvoie une dépendance FastAPI). Retirer l'ancien bloc `if not AGENT_API_KEY: return`.

2. Dans `execute_command`, **supprimer entièrement** la branche « Mode CAP v1 » (le bloc `if command and command.strip().startswith("{")` qui fusionne `entities` dans `cap_args` et appelle `execute_direct`). Conserver la branche structurée (`if request.function:`) et la branche naturelle finale.

3. La branche structurée appelle déjà `agent.execute_direct(request.function, request.args)` — la coercition ajoutée en Step 3 s'applique automatiquement.

- [ ] **Step 7 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/agents/test_agent_server_structured.py tests/agents/test_execute_direct_coercion.py -q && .venv/bin/mypy agents/base.py`
Expected: PASS ; mypy: Success.

- [ ] **Step 8 : Commit**

```bash
git add agents/base.py server.py tests/agents/test_execute_direct_coercion.py tests/agents/test_agent_server_structured.py
git commit -m "feat(agents): execute_direct coerce les args, serveur agent fail-closed, retrait CAP v1"
```

---

### Task 4 : Manifeste de capacités CrowdSec + conformance

**Files:**
- Create: `agents/manifests/crowdsec.yml`
- Create: `agents/manifest.py` (chargeur + conformance)
- Test: `tests/agents/test_manifest.py`

**Interfaces:**
- Consumes: `agents/crowdsec_agent.py::CrowdSecAgent.get_capabilities()` (existant : liste de `{name, required, ...}`).
- Produces:
  - `def load_manifest(agent_name: str) -> list[core.policy.catalog.Capability]` — lit `agents/manifests/<agent_name>.yml` et renvoie des `Capability(name="<agent>.<fn>", required_args=[...])`.
  - `class ManifestConformanceError(Exception)`.
  - `def check_conformance(agent_name: str, live_caps: list[dict]) -> None` — compare l'ensemble des fonctions déclarées (non qualifiées) et leurs `required_args` avec `live_caps` (chaque item a `name` + `required`). Écart → `ManifestConformanceError`.

- [ ] **Step 1 : Écrire le manifeste déclaré**

```yaml
# agents/manifests/crowdsec.yml
# Capacités déclarées de l'agent CrowdSec (source de vérité pour catalogue + conformance).
agent: crowdsec
capabilities:
  - name: ban_ip
    required_args: [ip]
  - name: unban_ip
    required_args: [ip]
  - name: get_decisions
    required_args: []
  - name: add_decision
    required_args: [value]
  - name: delete_decision
    required_args: [decision_id]
  - name: get_alerts
    required_args: []
  - name: get_alert
    required_args: [alert_id]
  - name: delete_alert
    required_args: [alert_id]
  - name: get_allowlists
    required_args: []
  - name: check_allowlist
    required_args: [ip_or_range]
  - name: list_bouncers
    required_args: []
  - name: list_machines
    required_args: []
  - name: get_metrics
    required_args: []
  - name: hub_upgrade
    required_args: []
  - name: set_simulation
    required_args: [action]
```

- [ ] **Step 2 : Écrire le test qui échoue**

```python
# tests/agents/test_manifest.py
import pytest
from agents.manifest import load_manifest, check_conformance, ManifestConformanceError
from agents.crowdsec_agent import CrowdSecAgent


def test_load_manifest_namespaces():
    caps = load_manifest("crowdsec")
    names = {c.name for c in caps}
    assert "crowdsec.ban_ip" in names
    ban = next(c for c in caps if c.name == "crowdsec.ban_ip")
    assert ban.required_args == ["ip"]
    assert len(caps) == 15


def test_conformance_matches_live_agent():
    agent = CrowdSecAgent(model_path=None)
    check_conformance("crowdsec", agent.get_capabilities())  # ne lève pas


def test_conformance_detects_drift():
    live = [{"name": "ban_ip", "required": ["ip", "SURPRISE"]}]
    with pytest.raises(ManifestConformanceError):
        check_conformance("crowdsec", live)
```

- [ ] **Step 3 : Lancer le test, vérifier l'échec**

Run: `.venv/bin/pytest tests/agents/test_manifest.py -q`
Expected: FAIL (`No module named 'agents.manifest'`).

- [ ] **Step 4 : Implémenter `agents/manifest.py`**

```python
"""Manifestes de capacités déclarés — source de vérité du catalogue + conformance.

Le catalogue de politique se construit depuis ces déclarations (déterministe,
indépendant de la disponibilité des agents). Au démarrage, on vérifie que le
`get_capabilities()` live d'un agent correspond à sa déclaration (détection de
drift → refus de démarrer).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from core.policy.catalog import Capability

_MANIFEST_DIR = Path(__file__).parent / "manifests"


class ManifestConformanceError(Exception):
    """Le manifeste déclaré et les capacités live de l'agent divergent."""


def _declared(agent_name: str) -> dict[str, list[str]]:
    path = _MANIFEST_DIR / f"{agent_name}.yml"
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {c["name"]: list(c.get("required_args", [])) for c in data["capabilities"]}


def load_manifest(agent_name: str) -> list[Capability]:
    declared = _declared(agent_name)
    return [
        Capability(name=f"{agent_name}.{fn}", required_args=req)
        for fn, req in declared.items()
    ]


def check_conformance(agent_name: str, live_caps: list[dict[str, Any]]) -> None:
    declared = _declared(agent_name)
    live = {c["name"]: sorted(c.get("required", [])) for c in live_caps}
    declared_sorted = {fn: sorted(req) for fn, req in declared.items()}
    if live.keys() != declared_sorted.keys():
        missing = declared_sorted.keys() ^ live.keys()
        raise ManifestConformanceError(f"{agent_name}: fonctions divergentes {missing}")
    for fn, req in declared_sorted.items():
        if live[fn] != req:
            raise ManifestConformanceError(
                f"{agent_name}.{fn}: required déclaré {req} != live {live[fn]}"
            )
```

- [ ] **Step 5 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/agents/test_manifest.py -q && .venv/bin/mypy agents/manifest.py`
Expected: PASS ; mypy: Success.

Note : si `test_conformance_matches_live_agent` échoue sur un écart réel (ex. `required` live inclut un arg que le manifeste omet), corriger le **manifeste** pour refléter la signature réelle — le manifeste doit être exact, c'est le contrat.

- [ ] **Step 6 : Commit**

```bash
git add agents/manifests/crowdsec.yml agents/manifest.py tests/agents/test_manifest.py
git commit -m "feat(agents/manifest): capacites crowdsec declarees + verification de conformance"
```

---

### Task 5 : Extraire `core/decision.py` (DRY boucle ↔ orchestrateur)

**Files:**
- Create: `core/decision.py`
- Modify: `core/orchestrator.py` (utiliser `decide`)
- Test: `tests/core/test_decision.py`

**Interfaces:**
- Consumes: `core.policy.catalog.CapabilityCatalog`, `core.policy.engine.evaluate`, `core.audit.sink.AuditSink`, `core.audit.sink.entry_from_verdict`, `core.policy.models.{Intention,Rule,Verdict}`.
- Produces: `def decide(intention: Intention, *, catalog: CapabilityCatalog, policy: list[Rule], sink: AuditSink, event: str = "policy_decision") -> Verdict` — valide l'intention contre le catalogue (lève `UnknownCapability`/`MissingArgs`), évalue la politique, écrit l'entrée d'audit, renvoie le verdict. Utilisé par `TrustOrchestrator.handle` **et** la boucle gatée.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/core/test_decision.py
from core.decision import decide
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import Intention, Match, Rule
from core.audit.sink import MemoryAuditSink


def _catalog():
    return CapabilityCatalog([Capability(name="crowdsec.ban_ip", required_args=["ip"])])


def test_decide_allows_and_audits():
    sink = MemoryAuditSink()
    policy = [Rule(match=Match(capability="crowdsec.ban_ip"), effect="allow")]
    v = decide(Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"}),
               catalog=_catalog(), policy=policy, sink=sink)
    assert v.effect == "allow"
    assert sink.entries[-1].capability == "crowdsec.ban_ip"


def test_decide_default_deny():
    sink = MemoryAuditSink()
    v = decide(Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"}),
               catalog=_catalog(), policy=[], sink=sink)
    assert v.effect == "deny"
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_decision.py -q`
Expected: FAIL (`No module named 'core.decision'`).

- [ ] **Step 3 : Implémenter `core/decision.py`**

```python
"""Séquence de décision partagée : valider → évaluer → auditer → verdict.

Extraite pour que l'orchestrateur mono-action ET la boucle ReAct gatée du
coordinateur partagent exactement la même logique (DRY), sans dupliquer l'ordre
validation/évaluation/audit.
"""

from __future__ import annotations

from core.audit.sink import AuditSink, entry_from_verdict
from core.policy.catalog import CapabilityCatalog
from core.policy.engine import evaluate
from core.policy.models import Intention, Rule, Verdict


def decide(
    intention: Intention,
    *,
    catalog: CapabilityCatalog,
    policy: list[Rule],
    sink: AuditSink,
    event: str = "policy_decision",
) -> Verdict:
    """Valide l'intention (lève si capacité/args invalides), évalue, audite, renvoie."""
    catalog.validate_intention(intention)
    verdict = evaluate(intention, policy)
    sink.write(entry_from_verdict(verdict, event=event))
    return verdict
```

- [ ] **Step 4 : Refactorer `TrustOrchestrator.handle` pour utiliser `decide`**

Dans `core/orchestrator.py`, remplacer les trois lignes de `handle` :

```python
        self._catalog.validate_intention(intention)
        verdict = evaluate(intention, self._policy)
        self._sink.write(entry_from_verdict(verdict, event="policy_decision"))
```

par :

```python
        from core.decision import decide
        verdict = decide(
            intention, catalog=self._catalog, policy=self._policy, sink=self._sink
        )
```

Retirer les imports devenus inutiles dans `orchestrator.py` **seulement s'ils ne servent plus ailleurs** (`evaluate`, `entry_from_verdict` restent utilisés par `resume`/`reject` via `entry_from_verdict` — vérifier ; `evaluate` n'est plus utilisé ailleurs → le retirer). Utiliser `.venv/bin/ruff check core/orchestrator.py` pour confirmer l'absence d'import mort.

- [ ] **Step 5 : Lancer les tests (nouveau + non-régression A), vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_decision.py tests/core/test_orchestrator.py -q && .venv/bin/mypy core/decision.py core/orchestrator.py && .venv/bin/ruff check core/orchestrator.py core/decision.py`
Expected: PASS (les tests A de l'orchestrateur restent verts) ; mypy: Success ; ruff: clean.

- [ ] **Step 6 : Commit**

```bash
git add core/decision.py core/orchestrator.py tests/core/test_decision.py
git commit -m "refactor(core/decision): extraire la sequence valider-evaluer-auditer (DRY)"
```

---

### Task 6 : Adaptateur `AgentCall` (`coordinator/agent_call.py`)

**Files:**
- Create: `coordinator/agent_call.py`
- Test: `tests/coordinator/test_agent_call.py`
- Create: `tests/coordinator/__init__.py` (si absent)

**Interfaces:**
- Consumes: `coordinator/clients/tool_agent_client.py::ToolAgentClient.execute_structured(function, args) -> dict`.
- Produces:
  - `class UnknownAgent(Exception)`.
  - `def make_agent_call(clients: Mapping[str, ClientLike]) -> AgentCall` où `AgentCall = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]`. Le `capability` reçu est qualifié (`crowdsec.ban_ip`) : l'adaptateur sépare sur le premier `.` → agent + fonction, choisit le client, appelle `execute_structured(fonction, real_args)`, renvoie le dict. Agent inconnu → `UnknownAgent`. `ClientLike` = Protocol avec `async def execute_structured(self, function: str, args: dict[str, Any]) -> dict[str, Any]`.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/coordinator/test_agent_call.py
import pytest
from coordinator.agent_call import make_agent_call, UnknownAgent


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def execute_structured(self, function, args):
        self.calls.append((function, args))
        return {"success": True, "function": function, "args": args}


@pytest.mark.asyncio
async def test_splits_namespace_and_routes():
    fake = _FakeClient()
    call = make_agent_call({"crowdsec": fake})
    out = await call("crowdsec.ban_ip", {"ip": "203.0.113.9"})
    assert fake.calls == [("ban_ip", {"ip": "203.0.113.9"})]
    assert out["function"] == "ban_ip"


@pytest.mark.asyncio
async def test_unknown_agent_raises():
    call = make_agent_call({"crowdsec": _FakeClient()})
    with pytest.raises(UnknownAgent):
        await call("opnsense.add_nat", {})
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `.venv/bin/pytest tests/coordinator/test_agent_call.py -q`
Expected: FAIL (`No module named 'coordinator.agent_call'`).

- [ ] **Step 3 : Implémenter `coordinator/agent_call.py`**

```python
"""Adaptateur entre la frontière d'exécution de `core/` et le transport agent.

`core.execution.execute` appelle `call(capability, real_args)` avec une capacité
QUALIFIÉE (`crowdsec.ban_ip`). L'agent, lui, ne connaît que ses fonctions non
qualifiées. Cet adaptateur sépare le namespace, choisit le bon client, et délègue
à `execute_structured` (mode CAP v2, sans SLM).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

AgentCall = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]


class ClientLike(Protocol):
    async def execute_structured(self, function: str, args: dict[str, Any]) -> dict[str, Any]: ...


class UnknownAgent(Exception):
    """La capacité vise un agent absent de la table de clients."""


def make_agent_call(clients: Mapping[str, ClientLike]) -> AgentCall:
    async def _call(capability: str, args: dict[str, str]) -> dict[str, Any]:
        agent_name, _, function = capability.partition(".")
        if not function or agent_name not in clients:
            raise UnknownAgent(capability)
        return await clients[agent_name].execute_structured(function, args)

    return _call
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/coordinator/test_agent_call.py -q && .venv/bin/mypy coordinator/agent_call.py`
Expected: PASS ; mypy: Success.

- [ ] **Step 5 : Commit**

```bash
git add coordinator/agent_call.py tests/coordinator/
git commit -m "feat(coordinator/agent_call): router les capacites qualifiees vers execute_structured"
```

---

### Task 7 : Proposer (`coordinator/proposer.py`)

**Files:**
- Create: `coordinator/proposer.py`
- Test: `tests/coordinator/test_proposer.py`

**Interfaces:**
- Consumes: `core.policy.catalog.CapabilityCatalog`, `core.policy.models.Intention`.
- Produces:
  - `class Act(BaseModel)` : `intention: Intention`.
  - `class Finish(BaseModel)` : `summary: str`.
  - `Proposal = Act | Finish`.
  - `class ChatLLM(Protocol)` : `async def chat(self, messages: list[dict[str, str]], max_tokens: int = 1024) -> str`.
  - `class ProposerError(Exception)`.
  - `class LlmProposer` : `__init__(self, *, llm: ChatLLM, catalog: CapabilityCatalog, max_retries: int = 2)` ; `async def propose(self, request_tokens: str, history: list[str]) -> Proposal`. Construit les messages (system : instructions + liste des capacités du catalogue + format JSON attendu ; user : requête tokenisée ; observations : history), appelle `llm.chat`, parse le JSON. Le JSON attendu : `{"action": {"capability": "...", "args": {...}}}` **ou** `{"final": "résumé"}`. Valide l'intention via `catalog.validate_intention`. JSON invalide / capacité inconnue / args manquants → nouvel essai (jusqu'à `max_retries`), l'erreur étant réinjectée en message ; épuisement → `ProposerError`.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/coordinator/test_proposer.py
import json
import pytest
from coordinator.proposer import LlmProposer, Act, Finish, ProposerError
from core.policy.catalog import Capability, CapabilityCatalog


class _ScriptedLLM:
    def __init__(self, replies):
        self._replies = list(replies)
        self.seen = []

    async def chat(self, messages, max_tokens=1024):
        self.seen.append(messages)
        return self._replies.pop(0)


def _catalog():
    return CapabilityCatalog([Capability(name="crowdsec.ban_ip", required_args=["ip"])])


@pytest.mark.asyncio
async def test_parses_action():
    llm = _ScriptedLLM([json.dumps({"action": {"capability": "crowdsec.ban_ip", "args": {"ip": "IP_1"}}})])
    p = LlmProposer(llm=llm, catalog=_catalog())
    prop = await p.propose("banni IP_1", [])
    assert isinstance(prop, Act)
    assert prop.intention.capability == "crowdsec.ban_ip"
    assert prop.intention.args == {"ip": "IP_1"}


@pytest.mark.asyncio
async def test_parses_finish():
    llm = _ScriptedLLM([json.dumps({"final": "terminé"})])
    p = LlmProposer(llm=llm, catalog=_catalog())
    prop = await p.propose("rien", [])
    assert isinstance(prop, Finish)
    assert prop.summary == "terminé"


@pytest.mark.asyncio
async def test_retries_on_invalid_then_succeeds():
    llm = _ScriptedLLM([
        "pas du json",
        json.dumps({"action": {"capability": "crowdsec.unknown", "args": {}}}),
        json.dumps({"action": {"capability": "crowdsec.ban_ip", "args": {"ip": "IP_1"}}}),
    ])
    p = LlmProposer(llm=llm, catalog=_catalog(), max_retries=2)
    prop = await p.propose("banni IP_1", [])
    assert isinstance(prop, Act)
    assert len(llm.seen) == 3


@pytest.mark.asyncio
async def test_exhausts_retries():
    llm = _ScriptedLLM(["nope", "nope", "nope"])
    p = LlmProposer(llm=llm, catalog=_catalog(), max_retries=2)
    with pytest.raises(ProposerError):
        await p.propose("x", [])
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `.venv/bin/pytest tests/coordinator/test_proposer.py -q`
Expected: FAIL (`No module named 'coordinator.proposer'`).

- [ ] **Step 3 : Implémenter `coordinator/proposer.py`**

```python
"""Proposer — adapte un LLM brut en producteur d'intentions validées.

Le LLM ne DÉCIDE rien : il PROPOSE. Sa sortie JSON est parsée, validée contre le
catalogue, et convertie en `core.Intention` (args = jetons). Une sortie invalide
déclenche un nouvel essai borné, l'erreur étant réinjectée pour guider le LLM.
"""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from core.policy.catalog import CapabilityCatalog, MissingArgs, UnknownCapability
from core.policy.models import Intention


class Act(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    intention: Intention


class Finish(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    summary: str


Proposal = Act | Finish


class ChatLLM(Protocol):
    async def chat(self, messages: list[dict[str, str]], max_tokens: int = 1024) -> str: ...


class ProposerError(Exception):
    """Le LLM n'a pas produit de proposition valide dans le budget d'essais."""


_SYSTEM = (
    "Tu es un proposeur d'actions de sécurité réseau. Tu ne vois que des JETONS "
    "(IP_1, VPN_USER_2) — jamais de valeurs réelles ; recopie-les tels quels. "
    "À chaque tour, réponds STRICTEMENT en JSON, soit une action :\n"
    '  {"action": {"capability": "<nom>", "args": {"<arg>": "<jeton|valeur>"}}}\n'
    "soit la fin du plan :\n"
    '  {"final": "<résumé>"}\n'
    "Capacités autorisées : {capabilities}. Aucun texte hors du JSON."
)


class LlmProposer:
    def __init__(self, *, llm: ChatLLM, catalog: CapabilityCatalog, max_retries: int = 2) -> None:
        self._llm = llm
        self._catalog = catalog
        self._max_retries = max_retries

    def _system_message(self) -> dict[str, str]:
        caps = ", ".join(self._catalog.names())
        return {"role": "system", "content": _SYSTEM.format(capabilities=caps)}

    def _base_messages(self, request_tokens: str, history: list[str]) -> list[dict[str, str]]:
        msgs = [self._system_message(), {"role": "user", "content": request_tokens}]
        for obs in history:
            msgs.append({"role": "user", "content": f"OBSERVATION: {obs}"})
        return msgs

    def _parse(self, raw: str) -> Proposal:
        data = json.loads(raw)  # lève JSONDecodeError si invalide
        if "final" in data:
            return Finish(summary=str(data["final"]))
        action = data["action"]  # lève KeyError si absent
        intention = Intention(capability=action["capability"], args=action.get("args", {}))
        self._catalog.validate_intention(intention)  # lève UnknownCapability/MissingArgs
        return Act(intention=intention)

    async def propose(self, request_tokens: str, history: list[str]) -> Proposal:
        messages = self._base_messages(request_tokens, history)
        last_error = ""
        for attempt in range(self._max_retries + 1):
            if last_error:
                messages = [
                    *self._base_messages(request_tokens, history),
                    {"role": "user", "content": f"Ta réponse précédente était invalide ({last_error}). Recommence en JSON strict."},
                ]
            raw = await self._llm.chat(messages)
            try:
                return self._parse(raw)
            except (json.JSONDecodeError, KeyError, TypeError, ValidationError,
                    UnknownCapability, MissingArgs) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
        raise ProposerError(last_error)
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/coordinator/test_proposer.py -q && .venv/bin/mypy coordinator/proposer.py`
Expected: PASS ; mypy: Success.

- [ ] **Step 5 : Commit**

```bash
git add coordinator/proposer.py tests/coordinator/test_proposer.py
git commit -m "feat(coordinator/proposer): LLM vers intention validee avec retry borne"
```

---

### Task 8 : Constructeur de catalogue + conformance au démarrage

**Files:**
- Create: `coordinator/catalog_builder.py`
- Test: `tests/coordinator/test_catalog_builder.py`

**Interfaces:**
- Consumes: `agents/manifest.py::{load_manifest, check_conformance, ManifestConformanceError}`, `core.policy.catalog.CapabilityCatalog`.
- Produces:
  - `class CapsClientLike(Protocol)` : `async def get_capabilities(self) -> dict[str, Any]` (le dict live du serveur d'agent : `{"agents": [{"tool": "<name>", "functions": [{"name","required",...}]}]}` — voir note).
  - `async def build_catalog(agent_names: list[str], live_caps: Mapping[str, list[dict]]) -> CapabilityCatalog` — pour chaque agent : `load_manifest` + `check_conformance(agent, live_caps[agent])` ; agrège les `Capability` en un `CapabilityCatalog`. Un agent absent de `live_caps` (injoignable) est **ignoré pour la conformance** mais ses capacités déclarées entrent quand même dans le catalogue (la politique reste stable). Drift → propage `ManifestConformanceError` (refus de démarrer).

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/coordinator/test_catalog_builder.py
import pytest
from coordinator.catalog_builder import build_catalog
from agents.manifest import ManifestConformanceError
from agents.crowdsec_agent import CrowdSecAgent


@pytest.mark.asyncio
async def test_build_catalog_from_live_agent():
    live = {"crowdsec": CrowdSecAgent(model_path=None).get_capabilities()}
    catalog = await build_catalog(["crowdsec"], live)
    assert "crowdsec.ban_ip" in catalog.names()
    assert len(catalog.names()) == 15


@pytest.mark.asyncio
async def test_unreachable_agent_still_in_catalog():
    catalog = await build_catalog(["crowdsec"], {})  # aucun live → pas de conformance
    assert "crowdsec.ban_ip" in catalog.names()


@pytest.mark.asyncio
async def test_drift_refuses():
    live = {"crowdsec": [{"name": "ban_ip", "required": ["ip", "DRIFT"]}]}
    with pytest.raises(ManifestConformanceError):
        await build_catalog(["crowdsec"], live)
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `.venv/bin/pytest tests/coordinator/test_catalog_builder.py -q`
Expected: FAIL (`No module named 'coordinator.catalog_builder'`).

- [ ] **Step 3 : Implémenter `coordinator/catalog_builder.py`**

```python
"""Construction du catalogue de capacités + conformance au démarrage.

Le catalogue vient des manifestes DÉCLARÉS (déterministe). Pour chaque agent
joignable, on vérifie que son `get_capabilities()` live correspond à sa
déclaration ; un drift refuse le démarrage. Un agent injoignable n'invalide pas
le démarrage : ses capacités déclarées restent dans le catalogue (la politique
ne bouge pas), et un appel réel échouera proprement à l'exécution.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agents.manifest import check_conformance, load_manifest
from core.policy.catalog import Capability, CapabilityCatalog


async def build_catalog(
    agent_names: list[str],
    live_caps: Mapping[str, list[dict[str, Any]]],
) -> CapabilityCatalog:
    caps: list[Capability] = []
    for name in agent_names:
        caps.extend(load_manifest(name))
        if name in live_caps:
            check_conformance(name, live_caps[name])  # lève ManifestConformanceError sur drift
    return CapabilityCatalog(caps)
```

Note : le format live de `GET /capabilities` du serveur agrège plusieurs agents ; l'appelant (Task 11) extrait la liste `functions` de l'agent voulu et la passe ici. Le test utilise directement `agent.get_capabilities()` qui renvoie la liste `[{name, required, ...}]`.

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/coordinator/test_catalog_builder.py -q && .venv/bin/mypy coordinator/catalog_builder.py`
Expected: PASS ; mypy: Success.

- [ ] **Step 5 : Commit**

```bash
git add coordinator/catalog_builder.py tests/coordinator/test_catalog_builder.py
git commit -m "feat(coordinator/catalog_builder): catalogue declare + conformance au demarrage"
```

---

### Task 9 : `SessionStore` + snapshot du vault (`coordinator/session.py`, `core/tokens/vault.py`)

**Files:**
- Modify: `core/tokens/vault.py` (snapshot/restore)
- Create: `coordinator/session.py`
- Test: `tests/core/test_vault_snapshot.py`
- Test: `tests/coordinator/test_session.py`
- Modify: `pyproject.toml` (dépendance `cryptography`)

**Interfaces:**
- Produces (vault) : `Vault.snapshot(self) -> dict[str, Any]` ; `@classmethod Vault.restore(cls, snap: dict[str, Any]) -> Vault`. Round-trip exact de `_to_real`/`_to_token`/`_counters`.
- Produces (session) :
  - `class SessionState(BaseModel)` : `id: str` ; `request_tokens: str` ; `vault_snapshot: dict[str, Any]` ; `history: list[str]` ; `step: int` ; `expires_at: float`.
  - `Clock = Callable[[], float]`.
  - `class SessionStore(Protocol)` : `def save(self, state: SessionState) -> None` ; `def get(self, session_id: str, *, now: float) -> SessionState | None` (renvoie `None` et purge si `expires_at <= now`) ; `def delete(self, session_id: str) -> None`.
  - `class MemorySessionStore` — implémentation en mémoire (tests).
  - `class EncryptedFileSessionStore` — `__init__(self, directory: Path, key: bytes)` ; sérialise `SessionState` en JSON chiffré Fernet, un fichier par session.
  - `def load_session_key(env: Mapping[str, str], var: str = "COORDINATOR_SESSION_KEY") -> bytes` — lève `SessionKeyNotConfigured` si absent.

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/core/test_vault_snapshot.py
from core.tokens.vault import Vault


def test_vault_snapshot_roundtrip():
    v = Vault()
    t = v.token_for("IP", "203.0.113.9")
    restored = Vault.restore(v.snapshot())
    assert restored.resolve(t) == "203.0.113.9"
    # la numérotation continue sans collision
    assert restored.token_for("IP", "198.51.100.4") != t
```

```python
# tests/coordinator/test_session.py
import pytest
from pathlib import Path
from coordinator.session import (
    SessionState, MemorySessionStore, EncryptedFileSessionStore, load_session_key,
    SessionKeyNotConfigured,
)
from cryptography.fernet import Fernet


def _state(exp=100.0):
    return SessionState(id="s1", request_tokens="banni IP_1", vault_snapshot={},
                        history=[], step=0, expires_at=exp)


def test_memory_expiry_purges():
    store = MemorySessionStore()
    store.save(_state(exp=100.0))
    assert store.get("s1", now=50.0) is not None
    assert store.get("s1", now=150.0) is None
    assert store.get("s1", now=50.0) is None  # purgé


def test_encrypted_file_roundtrip(tmp_path: Path):
    store = EncryptedFileSessionStore(tmp_path, Fernet.generate_key())
    store.save(_state())
    got = store.get("s1", now=50.0)
    assert got is not None and got.request_tokens == "banni IP_1"
    # le fichier sur disque ne contient pas le clair
    blob = (tmp_path / "s1.session").read_bytes()
    assert b"banni" not in blob


def test_load_key_fail_closed():
    with pytest.raises(SessionKeyNotConfigured):
        load_session_key({}, "COORDINATOR_SESSION_KEY")
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_vault_snapshot.py tests/coordinator/test_session.py -q`
Expected: FAIL (`Vault.restore` absent ; `No module named 'coordinator.session'`).

- [ ] **Step 3 : Ajouter snapshot/restore à `Vault`**

Dans `core/tokens/vault.py`, ajouter à la classe `Vault` :

```python
    def snapshot(self) -> dict[str, Any]:
        """État sérialisable du vault (pour persistance de session)."""
        return {"to_real": dict(self._to_real), "counters": dict(self._counters)}

    @classmethod
    def restore(cls, snap: dict[str, Any]) -> "Vault":
        v = cls()
        v._to_real = dict(snap.get("to_real", {}))
        v._to_token = {real: tok for tok, real in v._to_real.items()}
        v._counters = dict(snap.get("counters", {}))
        return v
```

- [ ] **Step 4 : Implémenter `coordinator/session.py`**

```python
"""Persistance de session pour la boucle gatée — chiffrée au repos, à échéance.

Une session suspendue (verdict `approve`) contient le mapping jeton→valeur réelle
(PII) : elle est chiffrée sur disque (Fernet) et porte une échéance. Une session
expirée est purgée à la lecture (ses jetons disparaissent) — c'est la réponse à la
fuite de vault des approbations jamais résolues.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict

Clock = Callable[[], float]


class SessionKeyNotConfigured(Exception):
    """Clé de chiffrement de session absente — le coordinateur ne doit pas démarrer."""


class SessionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    request_tokens: str
    vault_snapshot: dict[str, Any]
    history: list[str]
    step: int
    expires_at: float


class SessionStore(Protocol):
    def save(self, state: SessionState) -> None: ...
    def get(self, session_id: str, *, now: float) -> SessionState | None: ...
    def delete(self, session_id: str) -> None: ...


class MemorySessionStore:
    def __init__(self) -> None:
        self._by_id: dict[str, SessionState] = {}

    def save(self, state: SessionState) -> None:
        self._by_id[state.id] = state

    def get(self, session_id: str, *, now: float) -> SessionState | None:
        state = self._by_id.get(session_id)
        if state is None:
            return None
        if state.expires_at <= now:
            self.delete(session_id)
            return None
        return state

    def delete(self, session_id: str) -> None:
        self._by_id.pop(session_id, None)


class EncryptedFileSessionStore:
    def __init__(self, directory: Path, key: bytes) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(key)

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.session"

    def save(self, state: SessionState) -> None:
        blob = self._fernet.encrypt(state.model_dump_json().encode("utf-8"))
        self._path(state.id).write_bytes(blob)

    def get(self, session_id: str, *, now: float) -> SessionState | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        data = json.loads(self._fernet.decrypt(path.read_bytes()).decode("utf-8"))
        state = SessionState.model_validate(data)
        if state.expires_at <= now:
            self.delete(session_id)
            return None
        return state

    def delete(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)


def load_session_key(env: Mapping[str, str], var: str = "COORDINATOR_SESSION_KEY") -> bytes:
    raw = env.get(var, "")
    if not raw:
        raise SessionKeyNotConfigured(f"{var} absent : le coordinateur refuse de démarrer")
    return raw.encode("utf-8")
```

- [ ] **Step 5 : Ajouter la dépendance `cryptography`**

Dans `pyproject.toml`, ajouter à `[project].dependencies` : `"cryptography>=42.0.0"`. Puis `.venv/bin/pip install -e .` (ou `.venv/bin/pip install "cryptography>=42.0.0"`).

- [ ] **Step 6 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/core/test_vault_snapshot.py tests/coordinator/test_session.py -q && .venv/bin/mypy coordinator/session.py core/tokens/vault.py`
Expected: PASS ; mypy: Success.

- [ ] **Step 7 : Commit**

```bash
git add core/tokens/vault.py coordinator/session.py pyproject.toml tests/core/test_vault_snapshot.py tests/coordinator/test_session.py
git commit -m "feat(coordinator/session): store de session chiffre a echeance + snapshot du vault"
```

---

### Task 10 : Boucle ReAct gatée (`coordinator/loop.py`)

**Files:**
- Create: `coordinator/loop.py`
- Test: `tests/coordinator/test_loop.py`

**Interfaces:**
- Consumes: `coordinator.proposer.{LlmProposer,Act,Finish,Proposal}`, `coordinator.session.{SessionStore,SessionState,Clock}`, `coordinator.agent_call.AgentCall`, `core.decision.decide`, `core.execution.authorization.{grant,grant_approved,NotAuthorized}`, `core.execution.boundary.execute`, `core.approval.store.ApprovalStore`, `core.audit.sink.{AuditSink,entry_from_verdict}`, `core.policy.models.{Rule,Verdict}`, `core.policy.catalog.CapabilityCatalog`, `core.tokens.vault.{Vault,tokenize}`, `core.tokens.vault.ExtractFn`.
- Produces:
  - Résultats typés : `class Completed(BaseModel)` (`summary: str`, `results: list[dict]`) ; `class Suspended(BaseModel)` (`approval_id: str`) ; `class Denied(BaseModel)` (`reason: str`) ; `class Failed(BaseModel)` (`reason: str`). `LoopResult = Completed | Suspended | Denied | Failed`.
  - `class ProposerLike(Protocol)` : `async def propose(self, request_tokens: str, history: list[str]) -> Proposal`.
  - `class GatedLoop` : `__init__(self, *, proposer, catalog, policy, sink, approvals, sessions, call, extract, clock, id_factory, max_steps=10, session_ttl=300.0)` ; `async def handle(self, request_text: str) -> LoopResult` ; `async def resume(self, approval_id: str) -> LoopResult` ; `def reject(self, approval_id: str) -> LoopResult`. `id_factory: Callable[[], str]` fournit les identifiants de session/approbation (déterministe en test).

Notes de conception :
- La session est **stockée sous la clé `approval_id`** au moment de la suspension (pour que `resume(approval_id)` la retrouve). L'`approval_id` et le `session_id` sont le même identifiant, fourni par `id_factory` puis passé à `approvals.create(intention, approval_id=...)`.
- Re-tokenisation d'un résultat : `tokenize(json.dumps(result, ensure_ascii=False), vault, extract)` — les valeurs réelles connues retrouvent leur jeton, les nouvelles valeurs sensibles en reçoivent un.
- `_run(...)` boucle depuis un `(vault, history, step)` donné, partagé par `handle` (départ à 0) et `resume` (reprise après le pas approuvé).

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# tests/coordinator/test_loop.py
import json
import itertools
import pytest
from coordinator.loop import GatedLoop, Completed, Suspended, Denied, Failed
from coordinator.proposer import Act, Finish
from coordinator.session import MemorySessionStore
from core.approval.store import ApprovalStore
from core.audit.sink import MemoryAuditSink
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import ArgMatch, Intention, Match, Rule


def _catalog():
    return CapabilityCatalog([
        Capability(name="crowdsec.ban_ip", required_args=["ip"]),
        Capability(name="crowdsec.get_metrics", required_args=[]),
    ])


class _ScriptedProposer:
    """Renvoie une proposition scriptée par pas ; ignore le prompt."""
    def __init__(self, proposals):
        self._it = iter(proposals)

    async def propose(self, request_tokens, history):
        return next(self._it)


def _extract(text):
    # extracteur trivial : repère un motif IP factice pour la tokenisation
    import re
    return {"IP": re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", text)}


def _ids():
    counter = itertools.count(1)
    return lambda: f"appr-{next(counter)}"


def _loop(proposer, policy, *, call=None, sessions=None, clock=None):
    async def _noop_call(cap, args):
        return {"ok": cap, "args": args}
    return GatedLoop(
        proposer=proposer, catalog=_catalog(), policy=policy,
        sink=MemoryAuditSink(), approvals=ApprovalStore(),
        sessions=sessions or MemorySessionStore(),
        call=call or _noop_call, extract=_extract,
        clock=clock or (lambda: 0.0), id_factory=_ids(),
        max_steps=5, session_ttl=300.0,
    )


@pytest.mark.asyncio
async def test_allow_then_finish_completes():
    proposer = _ScriptedProposer([
        Act(intention=Intention(capability="crowdsec.get_metrics", args={})),
        Finish(summary="fait"),
    ])
    policy = [Rule(match=Match(capability="crowdsec.get_metrics"), effect="allow")]
    res = await _loop(proposer, policy).handle("montre les métriques")
    assert isinstance(res, Completed)
    assert len(res.results) == 1


@pytest.mark.asyncio
async def test_deny_stops():
    proposer = _ScriptedProposer([Act(intention=Intention(capability="crowdsec.get_metrics", args={}))])
    res = await _loop(proposer, []).handle("x")  # politique vide → deny
    assert isinstance(res, Denied)


@pytest.mark.asyncio
async def test_approve_suspends_then_resume_completes():
    proposer = _ScriptedProposer([
        Act(intention=Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"})),
        Finish(summary="banni"),
    ])
    policy = [Rule(match=Match(capability="crowdsec.ban_ip"), effect="approve")]
    sessions = MemorySessionStore()
    loop = _loop(proposer, policy, sessions=sessions)
    res = await loop.handle("banni 203.0.113.9")
    assert isinstance(res, Suspended)
    loop._approvals.approve(res.approval_id, loop._approvals.get(res.approval_id).intention_hash)
    res2 = await loop.resume(res.approval_id)
    assert isinstance(res2, Completed)


@pytest.mark.asyncio
async def test_resume_expired_session_fails():
    proposer = _ScriptedProposer([Act(intention=Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"}))])
    policy = [Rule(match=Match(capability="crowdsec.ban_ip"), effect="approve")]
    clock_box = {"t": 0.0}
    loop = _loop(proposer, policy, clock=lambda: clock_box["t"])
    res = await loop.handle("banni 203.0.113.9")
    assert isinstance(res, Suspended)
    loop._approvals.approve(res.approval_id, loop._approvals.get(res.approval_id).intention_hash)
    clock_box["t"] = 10_000.0  # au-delà du TTL
    res2 = await loop.resume(res.approval_id)
    assert isinstance(res2, Failed)


@pytest.mark.asyncio
async def test_llm_never_sees_real_ip():
    seen = []

    class _Spy:
        async def propose(self, request_tokens, history):
            seen.append((request_tokens, tuple(history)))
            if len(seen) == 1:
                return Act(intention=Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"}))
            return Finish(summary="ok")

    policy = [Rule(match=Match(capability="crowdsec.ban_ip"), effect="allow")]

    async def _echo_call(cap, args):
        return {"echo_ip": args["ip"]}  # renvoie la vraie IP → doit être re-tokenisée

    res = await _loop(_Spy(), policy, call=_echo_call).handle("banni 203.0.113.9")
    assert isinstance(res, Completed)
    flat = json.dumps(seen, ensure_ascii=False)
    assert "203.0.113.9" not in flat  # ni requête ni observation ne fuit l'IP
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run: `.venv/bin/pytest tests/coordinator/test_loop.py -q`
Expected: FAIL (`No module named 'coordinator.loop'`).

- [ ] **Step 3 : Implémenter `coordinator/loop.py`**

```python
"""Boucle ReAct gatée — orchestrateur multi-pas du coordinateur.

Chaque pas : le Proposer propose (LLM → intention validée), `core.decide` rend un
verdict fail-closed. `deny` stoppe ; `approve` SUSPEND toute la boucle (session
persistée, à échéance) jusqu'à reprise humaine ; `allow` exécute via la frontière
`core.execution` puis re-tokenise le résultat pour le pas suivant. Le LLM ne voit
que des jetons.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from coordinator.agent_call import AgentCall
from coordinator.proposer import Act, Finish, Proposal
from coordinator.session import Clock, SessionState, SessionStore
from core.approval.store import ApprovalStore
from core.audit.sink import AuditSink, entry_from_verdict
from core.decision import decide
from core.execution.authorization import NotAuthorized, grant, grant_approved
from core.execution.boundary import execute
from core.policy.catalog import CapabilityCatalog
from core.policy.models import Rule, Verdict
from core.tokens.vault import ExtractFn, Vault, tokenize


class Completed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    results: list[dict]


class Suspended(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str


class Denied(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


class Failed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


LoopResult = Completed | Suspended | Denied | Failed


class GatedLoop:
    def __init__(  # noqa: PLR0913 — racine de composition de la boucle
        self,
        *,
        proposer: "ProposerLike",
        catalog: CapabilityCatalog,
        policy: list[Rule],
        sink: AuditSink,
        approvals: ApprovalStore,
        sessions: SessionStore,
        call: AgentCall,
        extract: ExtractFn,
        clock: Clock,
        id_factory: Callable[[], str],
        max_steps: int = 10,
        session_ttl: float = 300.0,
    ) -> None:
        self._proposer = proposer
        self._catalog = catalog
        self._policy = policy
        self._sink = sink
        self._approvals = approvals
        self._sessions = sessions
        self._call = call
        self._extract = extract
        self._clock = clock
        self._new_id = id_factory
        self._max_steps = max_steps
        self._ttl = session_ttl

    async def handle(self, request_text: str) -> LoopResult:
        vault = Vault()
        request_tokens = tokenize(request_text, vault, self._extract)
        return await self._run(vault, request_tokens, history=[], step=0, results=[])

    async def resume(self, approval_id: str) -> LoopResult:
        session = self._sessions.get(approval_id, now=self._clock())
        if session is None:
            return Failed(reason="session inconnue ou expirée")
        approval = self._approvals.get(approval_id)
        if approval is None:
            return Failed(reason="approbation inconnue")
        verdict = Verdict(effect="approve", matched_rule=None, intention=approval.intention)
        vault = Vault.restore(session.vault_snapshot)
        try:
            authorized = grant_approved(approval)
        except NotAuthorized:
            self._sink.write(entry_from_verdict(verdict, event="resume_refuse"))
            return Denied(reason=f"approbation en état {approval.state}")
        result = await execute(authorized, vault, self._call)
        self._approvals.mark_executed(approval_id)
        self._sessions.delete(approval_id)
        self._sink.write(entry_from_verdict(verdict, event="executed_after_approval"))
        history = [*session.history, self._retokenize(result, vault)]
        return await self._run(vault, session.request_tokens, history, session.step + 1, [result])

    def reject(self, approval_id: str) -> LoopResult:
        approval = self._approvals.get(approval_id)
        if approval is None:
            return Failed(reason="approbation inconnue")
        self._approvals.reject(approval_id)
        self._sessions.delete(approval_id)
        verdict = Verdict(effect="approve", matched_rule=None, intention=approval.intention)
        self._sink.write(entry_from_verdict(verdict, event="rejected"))
        return Denied(reason="rejeté par l'opérateur")

    def _retokenize(self, result: dict, vault: Vault) -> str:
        return tokenize(json.dumps(result, ensure_ascii=False), vault, self._extract)

    async def _run(
        self, vault: Vault, request_tokens: str, history: list[str], step: int, results: list[dict]
    ) -> LoopResult:
        while step < self._max_steps:
            proposal: Proposal = await self._proposer.propose(request_tokens, history)
            if isinstance(proposal, Finish):
                return Completed(summary=proposal.summary, results=results)
            intention = proposal.intention
            verdict = decide(
                intention, catalog=self._catalog, policy=self._policy, sink=self._sink
            )
            if verdict.effect == "deny":
                return Denied(reason=f"politique: {intention.capability}")
            if verdict.effect == "approve":
                sid = self._new_id()
                self._approvals.create(intention, approval_id=sid)
                self._sessions.save(SessionState(
                    id=sid, request_tokens=request_tokens, vault_snapshot=vault.snapshot(),
                    history=history, step=step, expires_at=self._clock() + self._ttl,
                ))
                return Suspended(approval_id=sid)
            result = await execute(grant(verdict), vault, self._call)
            self._sink.write(entry_from_verdict(verdict, event="executed"))
            results.append(result)
            history = [*history, self._retokenize(result, vault)]
            step += 1
        return Failed(reason="nombre de pas maximal atteint")


from typing import Protocol  # noqa: E402 — Protocol placé après pour lisibilité du flux


class ProposerLike(Protocol):
    async def propose(self, request_tokens: str, history: list[str]) -> Proposal: ...
```

Note d'implémentation : déplacer la déclaration `class ProposerLike(Protocol)` et son import `Protocol` **en haut** du fichier (avant `GatedLoop`) si ruff/mypy s'en plaignent ; le placer en bas ici n'est qu'une aide de lecture. Le test accède à `loop._approvals` — attribut privé exposé pour le test ; c'est acceptable pour un test unitaire de la boucle.

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/coordinator/test_loop.py -q && .venv/bin/mypy coordinator/loop.py`
Expected: PASS ; mypy: Success.

- [ ] **Step 5 : Commit**

```bash
git add coordinator/loop.py tests/coordinator/test_loop.py
git commit -m "feat(coordinator/loop): boucle ReAct gatee avec suspend/resume et re-tokenisation"
```

---

### Task 11 : App coordinateur recâblée + suppression du legacy

**Files:**
- Create: `coordinator/app.py`
- Modify: `pyproject.toml` (mypy `files` étendu à la surface B)
- Delete: `coordinator/pilot.py`, `coordinator/judge.py`
- Modify: `coordinator/models.py` (retirer CAP v1 `CoordinatorDirective` et `_EMPTY_ENTITIES`)
- Modify: `coordinator/server.py` → **remplacé** : le point d'entrée devient `coordinator/app.py` ; retirer `/api/logs`, l'ancien `verify_api_key` fail-open, l'usage de `PilotAgent`.
- Test: `tests/coordinator/test_app.py`

**Interfaces:**
- Consumes: `core.auth.api_key.{load_auth_secret, make_auth_dependency}`, `coordinator.loop.GatedLoop`, `coordinator.proposer.LlmProposer`, `coordinator.catalog_builder.build_catalog`, `coordinator.agent_call.make_agent_call`, `coordinator.session.{EncryptedFileSessionStore, load_session_key}`, `coordinator.clients.tool_agent_client.ToolAgentClient`, `coordinator.llm.coordinator_llm.CoordinatorLLM`.
- Produces:
  - `def build_app(*, loop: GatedLoop, auth_secret: str) -> FastAPI` — app FastAPI avec **dépendance d'auth globale** (`make_auth_dependency`) et routes : `POST /coordinator/execute` (`{"request": str}` → `loop.handle` → résultat sérialisé) ; `POST /coordinator/resume/{approval_id}` → `loop.resume` ; `POST /coordinator/reject/{approval_id}` → `loop.reject` ; `GET /coordinator/health` (sans auth). Aucune route ne renvoie de PII ; pas de `/api/logs`.

L'assemblage runtime complet (ouverture des `ToolAgentClient` UDS, `get_capabilities` live → `build_catalog`, chargement de la politique YAML, `EncryptedFileSessionStore`, `LlmProposer(llm=CoordinatorLLM())`, point d'entrée uvicorn) relève du **sous-projet D** (packaging/exploitation). B livre la fabrique testable `build_app` + tous les composants injectés ; le seam est net.

- [ ] **Step 1 : Pré-nettoyage — retirer CAP v1 de `coordinator/models.py`**

Supprimer `CoordinatorDirective`, `_EMPTY_ENTITIES` et leurs helpers de `coordinator/models.py`. Si le fichier devient vide de contenu utile, le supprimer et retirer ses imports ailleurs. Vérifier les usages :

Run: `grep -rn "CoordinatorDirective\|_EMPTY_ENTITIES\|from .models\|coordinator.models" --include='*.py' . | grep -v tests`
Traiter chaque usage (tous dans le legacy supprimé : `pilot.py`, `judge.py`, `tool_agent_client.execute_cap`). Retirer aussi `execute_cap` de `tool_agent_client.py` (chemin CAP v1) — `execute_structured` le remplace.

- [ ] **Step 2 : Écrire le test qui échoue**

```python
# tests/coordinator/test_app.py
import itertools
import pytest
from fastapi.testclient import TestClient
from coordinator.app import build_app
from coordinator.loop import GatedLoop
from coordinator.proposer import Act, Finish
from coordinator.session import MemorySessionStore
from core.approval.store import ApprovalStore
from core.audit.sink import MemoryAuditSink
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import Match, Rule, Intention


class _Proposer:
    def __init__(self, seq):
        self._it = iter(seq)

    async def propose(self, request_tokens, history):
        return next(self._it)


def _loop(seq, policy):
    async def _call(cap, args):
        return {"ok": cap}
    return GatedLoop(
        proposer=_Proposer(seq),
        catalog=CapabilityCatalog([Capability(name="crowdsec.get_metrics", required_args=[])]),
        policy=policy, sink=MemoryAuditSink(), approvals=ApprovalStore(),
        sessions=MemorySessionStore(), call=_call, extract=lambda t: {},
        clock=lambda: 0.0, id_factory=(lambda c=itertools.count(1): f"a{next(c)}"),
    )


def _client(loop):
    return TestClient(build_app(loop=loop, auth_secret="secret"))


def test_execute_requires_auth():
    loop = _loop([Finish(summary="x")], [])
    r = _client(loop).post("/coordinator/execute", json={"request": "hello"})
    assert r.status_code == 401


def test_execute_completes_with_auth():
    seq = [Act(intention=Intention(capability="crowdsec.get_metrics", args={})), Finish(summary="fini")]
    policy = [Rule(match=Match(capability="crowdsec.get_metrics"), effect="allow")]
    r = _client(_loop(seq, policy)).post(
        "/coordinator/execute", headers={"X-API-Key": "secret"}, json={"request": "métriques"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


def test_health_no_auth():
    assert _client(_loop([Finish(summary="x")], [])).get("/coordinator/health").status_code == 200
```

- [ ] **Step 3 : Lancer le test, vérifier l'échec**

Run: `.venv/bin/pytest tests/coordinator/test_app.py -q`
Expected: FAIL (`No module named 'coordinator.app'`).

- [ ] **Step 4 : Implémenter `coordinator/app.py`**

```python
"""App FastAPI du coordinateur — auth globale fail-closed, délègue à la boucle gatée.

Aucune route ne renvoie de valeur réelle : les résultats de la boucle sont déjà
tokenisés côté LLM ; les résultats d'exécution renvoyés à l'opérateur sont ceux de
l'agent (l'opérateur est autorisé). Plus de `/api/logs` (fuite PII de l'audit).
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from coordinator.loop import Completed, Denied, Failed, GatedLoop, LoopResult, Suspended
from core.auth.api_key import make_auth_dependency


class ExecuteRequest(BaseModel):
    request: str


def _serialize(result: LoopResult) -> dict[str, Any]:
    if isinstance(result, Completed):
        return {"status": "completed", "summary": result.summary, "results": result.results}
    if isinstance(result, Suspended):
        return {"status": "pending_approval", "approval_id": result.approval_id}
    if isinstance(result, Denied):
        return {"status": "denied", "reason": result.reason}
    return {"status": "failed", "reason": result.reason}


def build_app(*, loop: GatedLoop, auth_secret: str) -> FastAPI:
    require_auth = make_auth_dependency(auth_secret)
    app = FastAPI(title="Cyber Coordinator", version="2.0")

    @app.get("/coordinator/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/coordinator/execute", dependencies=[Depends(require_auth)])
    async def execute(req: ExecuteRequest) -> dict[str, Any]:
        return _serialize(await loop.handle(req.request))

    @app.post("/coordinator/resume/{approval_id}", dependencies=[Depends(require_auth)])
    async def resume(approval_id: str) -> dict[str, Any]:
        return _serialize(await loop.resume(approval_id))

    @app.post("/coordinator/reject/{approval_id}", dependencies=[Depends(require_auth)])
    async def reject(approval_id: str) -> dict[str, Any]:
        return _serialize(loop.reject(approval_id))

    return app
```

Ne PAS ajouter de `create_default_app` : `build_app(*, loop, auth_secret)` est le SEUL point public de B. Les imports `os`/`Path`/`load_auth_secret` du squelette ne servent qu'à `build_app` (garder uniquement ceux réellement utilisés — ruff F401). L'assemblage runtime complet (ouverture des `ToolAgentClient` UDS, `get_capabilities` live → `build_catalog`, chargement de la politique YAML, `EncryptedFileSessionStore`, `LlmProposer(llm=CoordinatorLLM())`, `make_agent_call(clients)`, point d'entrée uvicorn) relève du **sous-projet D** (packaging/exploitation). B livre la fabrique testable ; le seam est net.

- [ ] **Step 5 : Supprimer le legacy et repointer l'entrée**

```bash
git rm coordinator/pilot.py coordinator/judge.py coordinator/server.py coordinator/state.py
```

`coordinator/server.py` (ancienne app + `/api/logs` + auth fail-open + `PilotAgent`) est supprimé ; `coordinator/state.py` (`CheckpointStore`/`RunStatus`/`TaskStatus`, l'ancien mécanisme d'approbation remplacé par `core.approval` + `SessionStore`) devient orphelin (importé seulement par pilot/server supprimés — vérifié) et est supprimé aussi. Vérifier qu'aucun import résiduel ne subsiste : `grep -rn "coordinator.server\|coordinator.state\|coordinator.pilot\|coordinator.judge\|PilotAgent\|CoordinatorDirective" --include='*.py' . | grep -v /.venv/` doit être vide (hors la suppression du champ dans `models.py`). Aucun **test** n'importe ces modules (vérifié : la suite de tests ne référence que core/coordinator[B]/agents). Le point d'entrée uvicorn runtime est un livrable du sous-projet D. Corriger le commentaire périmé `agents/ner_extractor.py:5` qui cite `CoordinatorDirective.entities` (référence morte).

- [ ] **Step 6 : Étendre la couverture mypy à la surface B**

Dans `pyproject.toml`, `[tool.mypy]`, remplacer `files = ["core"]` par :

```toml
files = ["core", "coordinator/agent_call.py", "coordinator/proposer.py",
         "coordinator/catalog_builder.py", "coordinator/session.py",
         "coordinator/loop.py", "coordinator/app.py",
         "agents/contracts.py", "agents/coercion.py", "agents/manifest.py"]
```

- [ ] **Step 7 : Lancer les tests + typage + non-régression globale**

Run: `.venv/bin/pytest tests/coordinator tests/core tests/agents -q && .venv/bin/mypy && .venv/bin/ruff check core coordinator/agent_call.py coordinator/proposer.py coordinator/catalog_builder.py coordinator/session.py coordinator/loop.py coordinator/app.py agents/contracts.py agents/coercion.py agents/manifest.py`
Expected: PASS ; mypy: Success ; ruff: clean. Aucun import résiduel vers `pilot`/`judge`/`CoordinatorDirective`.

- [ ] **Step 8 : Commit**

```bash
git add -A
git commit -m "feat(coordinator/app): app fail-closed sur la boucle gatee, suppression pilot/judge/CAP v1"
```

---

### Task 12 : Test d'intégration bout-en-bout (non-régression PII)

**Files:**
- Test: `tests/coordinator/test_e2e.py`

**Interfaces:**
- Consumes: tout B (`GatedLoop`, `build_agent_call` sur un `CrowdSecAgent` réel en mode simulation, `LlmProposer` avec LLM scripté, `MemoryAuditSink`).

Objectif : dérouler requête → politique `approve` → suspension → approbation → reprise → exécution réelle (agent CrowdSec en mode simulation, sans LAPI) → audit, en prouvant qu'**aucune PII** n'apparaît dans l'audit ni dans ce que voit le LLM.

- [ ] **Step 1 : Écrire le test d'intégration**

```python
# tests/coordinator/test_e2e.py
import itertools
import json
import re
import pytest

from agents.crowdsec_agent import CrowdSecAgent
from coordinator.agent_call import make_agent_call
from coordinator.loop import GatedLoop, Suspended, Completed
from coordinator.proposer import Act, Finish
from coordinator.session import MemorySessionStore
from core.approval.store import ApprovalStore
from core.audit.sink import MemoryAuditSink
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import Match, Rule, Intention

REAL_IP = "203.0.113.9"


class _AgentClientAdapter:
    """Expose un CrowdSecAgent réel via l'interface execute_structured (mode simulation)."""
    def __init__(self, agent):
        self._agent = agent

    async def execute_structured(self, function, args):
        res = await self._agent.execute_direct(function, args)
        return {"success": res.success, "function": res.function, "result": res.result}


class _Proposer:
    def __init__(self):
        self._seen = []
        self._step = 0

    async def propose(self, request_tokens, history):
        self._seen.append((request_tokens, list(history)))
        self._step += 1
        if self._step == 1:
            # L'IP réelle a été tokenisée ; le LLM propose avec le jeton.
            token = re.search(r"IP_\d+", request_tokens).group(0)
            return Act(intention=Intention(capability="crowdsec.ban_ip", args={"ip": token}))
        return Finish(summary="IP bannie")

    def leaked(self):
        return REAL_IP in json.dumps(self._seen, ensure_ascii=False)


@pytest.mark.asyncio
async def test_end_to_end_ban_with_approval_no_pii_leak():
    agent = CrowdSecAgent(model_path=None)  # simulation : pas de LAPI
    call = make_agent_call({"crowdsec": _AgentClientAdapter(agent)})
    proposer = _Proposer()
    sink = MemoryAuditSink()
    approvals = ApprovalStore()
    policy = [Rule(match=Match(capability="crowdsec.ban_ip"), effect="approve")]

    loop = GatedLoop(
        proposer=proposer,
        catalog=CapabilityCatalog([Capability(name="crowdsec.ban_ip", required_args=["ip"])]),
        policy=policy, sink=sink, approvals=approvals, sessions=MemorySessionStore(),
        call=call, extract=lambda t: {"IP": re.findall(r"\b\d+\.\d+\.\d+\.\d+\b", t)},
        clock=lambda: 0.0, id_factory=(lambda c=itertools.count(1): f"a{next(c)}"),
    )

    suspended = await loop.handle(f"banni l'IP {REAL_IP}")
    assert isinstance(suspended, Suspended)

    approvals.approve(suspended.approval_id, approvals.get(suspended.approval_id).intention_hash)
    done = await loop.resume(suspended.approval_id)
    assert isinstance(done, Completed)
    # L'exécution réelle a reçu la vraie IP (mode simulation renvoie status banned).
    assert done.results[0]["result"]["status"] == "banned"

    # Non-régression PII : ni le LLM ni l'audit ne voient l'IP réelle.
    assert not proposer.leaked()
    audit_blob = json.dumps([e.model_dump() for e in sink.entries], ensure_ascii=False)
    assert REAL_IP not in audit_blob
    # L'audit ne porte que des jetons pour l'arg ip.
    ban_entries = [e for e in sink.entries if e.capability == "crowdsec.ban_ip"]
    assert ban_entries and all(re.fullmatch(r"IP_\d+", e.args.get("ip", "")) for e in ban_entries)
```

- [ ] **Step 2 : Lancer le test, vérifier le succès**

Run: `.venv/bin/pytest tests/coordinator/test_e2e.py -q`
Expected: PASS. Si l'IP réelle apparaît dans l'audit/proposer, c'est un défaut de tokenisation à corriger avant de continuer (le test est le garde-fou C2/C4).

- [ ] **Step 3 : Suite complète + typage + lint**

Run: `.venv/bin/pytest -q && .venv/bin/mypy && .venv/bin/ruff check .`
Expected: toute la suite verte ; mypy Success ; ruff clean.

- [ ] **Step 4 : Commit**

```bash
git add tests/coordinator/test_e2e.py
git commit -m "test(coordinator): integration bout-en-bout ban+approbation, non-regression PII"
```

---

## Auto-revue du plan (checklist auteur)

**Couverture du spec :**
- CAP v2 durci (extra=forbid, args str, bornes) → Task 1. ✅
- Coercition string→type → Task 2 (+ câblage Task 3). ✅
- Chemin structuré agent sans SLM + fail-closed + retrait CAP v1 → Task 3. ✅
- Manifeste déclaré + conformance → Task 4. ✅
- Proposer (parse/valide/retry, jetons) → Task 7. ✅
- Catalogue déclaré + conformance au démarrage → Task 8. ✅
- Boucle ReAct gatée + suspend/resume + re-tokenisation → Task 10. ✅
- Session persistée chiffrée à échéance + horloge injectable (dette A) → Task 9. ✅
- Auth globale fail-closed (deux serveurs) → Task 3 (agent) + Task 11 (coordinateur). ✅
- Suppression pilot/judge/CAP v1 + `/api/logs` → Task 11. ✅
- DRY décision → Task 5. AgentCall → Task 6. ✅
- Intégration bout-en-bout no-PII (C2/C4) → Task 12. ✅
- Fermeture C1/C4 (routes gardées) → Task 3 + Task 11. C3 (bundle) déjà traité (619ff73), contrôle : Task 11 ne sert aucun secret. ✅

**Dette reportée (documentée au spec)** : `create_default_app` câblage runtime complet (Task 11 note) ; retrait total de `_infer_with_ollama` → B2 ; OPNsense/WireGuard → B2 ; `SessionStore` sur KV réel, ISM, licence, multi-tenant → D ; `matched_rule.reason` post-approbation → à vérifier en Task 10 (l'audit `executed_after_approval` porte `matched_rule=None`, connu ; propagation → D).

**Cohérence des types** : `AgentCall = Callable[[str, dict[str,str]], Awaitable[dict[str,Any]]]` identique en Task 6 et consommé Task 10 ; `Proposal = Act | Finish` défini Task 7, consommé Task 10 ; `decide(...)` signature identique Task 5 et Task 10 ; `SessionState`/`SessionStore` Task 9 consommés Task 10.
