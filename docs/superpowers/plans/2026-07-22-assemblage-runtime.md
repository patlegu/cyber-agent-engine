# Assemblage runtime & configuration (D1) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre `cyber-agent-engine` réellement lançable de bout en bout : un `create_default_app` câblé (coordinateur), le câblage env→agent (serveur d'agents), config fail-closed, audit durable, extracteur PII regex, console script — sans GPU/factory, en gardant les 114 tests A+B+C verts.

**Architecture:** Le coordinateur assemble ses dépendances (proposeur, catalogue live, politique YAML, session store chiffré, audit JSONL, extracteur regex) dans le `lifespan` FastAPI (l'import reste léger, l'échec de démarrage est propre). Les routes lisent la boucle depuis `app.state.loop`. Le serveur d'agents injecte un `OpenAICompatClient` depuis l'env. Deux petites dettes (rule_reason à l'audit post-approbation, no-silent-simulation) sont repliées.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, httpx, PyYAML, cryptography (Fernet), pytest/pytest-asyncio.

## Global Constraints

- **CQI > 9, test-first.**
- **Fail-closed lisible** : secret/chemin obligatoire manquant → message clair (via `load_auth_secret`/`load_session_key`/`ConfigError`), jamais un crash opaque ; `policy.yml` invalide → refus de démarrer ; aucun agent découvert → refus.
- **L'invariant d'import léger de C est maintenu** : `import coordinator.app` ne charge aucune dep lourde au niveau module (assemblage réseau dans le `lifespan`). Le garde-fou `tests/test_portability.py` doit rester vert.
- **Le LLM ne voit que des jetons** : l'extracteur regex alimente la tokenisation ; l'audit ne porte que des jetons (invariant A par construction).
- **Non-régression** : les 114 tests A+B+C restent verts ; en particulier `tests/coordinator/test_app.py` (B) après le refactor de `build_app`.
- **ruff clean** sur chaque nouveau module ET son test ; mypy strict clean sur les nouveaux modules `core/`/`coordinator/` (via `.venv/bin/mypy`, périmètre `files`). Les modules legacy touchés (`server.py`, `agents/base.py`) portent une dette pré-existante hors périmètre — pas de nouvelle anomalie sur les lignes modifiées, pas de nettoyage global.
- **Commits** : `type(scope): sujet` minuscules, sans emoji, **sans** `Co-Authored-By`, **sans** mention d'IA. Docstrings en français.
- **DRY/YAGNI** : réutiliser `load_policy`/`build_catalog`/`make_agent_call`/`GatedLoop`/`build_app`/`EncryptedFileSessionStore`/`OpenAICompatClient` livrés en A/B/C. D1 = un seul client vers le serveur d'agents (le serveur héberge tous les agents ; multi-serveur par agent → D3).

## Extension du périmètre mypy

Chaque nouveau module `coordinator/*`/`core/*` de D1 est ajouté à la liste `[tool.mypy].files` de `pyproject.toml` dans la tâche qui le crée (le module doit exister avant d'être listé, sinon mypy échoue). Le vérifier par `.venv/bin/mypy` (sans argument) en fin de tâche.

---

### Task 1 : `FileAuditSink` — audit durable JSONL

**Files:**
- Create: `core/audit/file_sink.py`
- Test: `tests/core/test_file_sink.py`
- Modify: `pyproject.toml` (`[tool.mypy].files` += `core/audit/file_sink.py`)

**Interfaces:**
- Consumes: `core.audit.sink.AuditEntry` (A).
- Produces: `core/audit/file_sink.py::FileAuditSink(path: str | Path)` avec `write(self, entry: AuditEntry) -> None`. Implémente le Protocol `AuditSink` (append-only JSONL, une entrée par ligne).

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/core/test_file_sink.py
import json
from pathlib import Path

from core.audit.file_sink import FileAuditSink
from core.audit.sink import AuditEntry


def _entry(cap: str = "crowdsec.ban_ip") -> AuditEntry:
    return AuditEntry(event="executed", capability=cap, effect="allow",
                      rule_reason="r", args={"ip": "IP_1"})


def test_appends_one_json_line_per_entry(tmp_path: Path):
    p = tmp_path / "audit.jsonl"
    sink = FileAuditSink(p)
    sink.write(_entry())
    sink.write(_entry("crowdsec.get_metrics"))
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["capability"] == "crowdsec.ban_ip"
    assert json.loads(lines[1])["capability"] == "crowdsec.get_metrics"


def test_creates_parent_directory(tmp_path: Path):
    p = tmp_path / "nested" / "audit.jsonl"
    FileAuditSink(p).write(_entry())
    assert p.exists()


def test_only_tokens_no_real_value(tmp_path: Path):
    p = tmp_path / "audit.jsonl"
    FileAuditSink(p).write(_entry())
    assert "203.0.113" not in p.read_text(encoding="utf-8")  # aucune vraie IP
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/core/test_file_sink.py -q`
Expected: FAIL (`No module named 'core.audit.file_sink'`).

- [ ] **Step 3 : Implémenter `core/audit/file_sink.py`**

```python
"""Puits d'audit durable — append-only JSONL, jetons uniquement.

Implémente le Protocol ``AuditSink`` de ``core.audit.sink`` pour l'exploitation.
Chaque ``AuditEntry`` est écrite sur une ligne JSON, en mode append. Les entrées
ne portent que des jetons (invariant de ``AuditEntry``) — aucune valeur réelle
n'atteint le fichier.
"""

from __future__ import annotations

from pathlib import Path

from core.audit.sink import AuditEntry


class FileAuditSink:
    """Écrit chaque entrée d'audit sur une ligne JSON, append-only."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, entry: AuditEntry) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(entry.model_dump_json() + "\n")
```

- [ ] **Step 4 : Lancer, vérifier le succès + typage**

Run: `.venv/bin/pytest tests/core/test_file_sink.py -q && .venv/bin/mypy core/audit/file_sink.py && .venv/bin/ruff check core/audit/file_sink.py tests/core/test_file_sink.py`
Expected: PASS ; mypy Success ; ruff clean.

- [ ] **Step 5 : Étendre le périmètre mypy + commit**

Ajouter `"core/audit/file_sink.py"` à `[tool.mypy].files` dans `pyproject.toml`. Puis :
```bash
.venv/bin/mypy
git add core/audit/file_sink.py tests/core/test_file_sink.py pyproject.toml
git commit -m "feat(core/audit): puits d audit durable JSONL append-only"
```

---

### Task 2 : Extracteur PII regex

**Files:**
- Create: `coordinator/extractor.py`
- Test: `tests/coordinator/test_extractor.py`
- Modify: `pyproject.toml` (`[tool.mypy].files` += `coordinator/extractor.py`)

**Interfaces:**
- Consumes: `core.tokens.vault.ExtractFn` (= `Callable[[str], dict[str, list[str]]]`).
- Produces: `coordinator/extractor.py::build_regex_extractor() -> ExtractFn`. La fonction renvoyée mappe un texte vers `{label: [valeurs uniques, ordre d'apparition]}` pour les labels : `IP_ADDRESS`, `IP_SUBNET`, `MAC_ADDRESS`, `HOSTNAME`, `PORT_NUMBER`, `CVE`, `HASH`.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/coordinator/test_extractor.py
from coordinator.extractor import build_regex_extractor

extract = build_regex_extractor()


def test_ipv4():
    assert extract("banni 203.0.113.9")["IP_ADDRESS"] == ["203.0.113.9"]


def test_cidr_not_split_as_ip():
    out = extract("réseau 198.51.100.0/24")
    assert out["IP_SUBNET"] == ["198.51.100.0/24"]
    assert out.get("IP_ADDRESS", []) == []  # le CIDR ne doit pas ré-émettre l'IP nue


def test_mac_and_cve_and_hash():
    out = extract("hôte 00:1b:44:11:3a:b7 vuln CVE-2021-44228 hash d41d8cd98f00b204e9800998ecf8427e")
    assert out["MAC_ADDRESS"] == ["00:1b:44:11:3a:b7"]
    assert out["CVE"] == ["CVE-2021-44228"]
    assert out["HASH"] == ["d41d8cd98f00b204e9800998ecf8427e"]


def test_hostname_and_port():
    out = extract("connexion à srv-web-01.example.com:8443")
    assert "srv-web-01.example.com" in out["HOSTNAME"]
    assert "8443" in out["PORT_NUMBER"]


def test_dedupe_and_order():
    out = extract("1.2.3.4 puis 5.6.7.8 puis 1.2.3.4")
    assert out["IP_ADDRESS"] == ["1.2.3.4", "5.6.7.8"]


def test_no_false_positive_on_plain_words():
    out = extract("bonjour le monde")
    assert all(not v for v in out.values())
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/coordinator/test_extractor.py -q`
Expected: FAIL (`No module named 'coordinator.extractor'`).

- [ ] **Step 3 : Implémenter `coordinator/extractor.py`**

```python
"""Extracteur PII regex — déterministe, sans dépendance lourde.

Alimente la tokenisation du coordinateur : détecte les entités réseau sensibles
(IP, sous-réseau, MAC, hostname, port, CVE, hash) et les rend par label. Calibré
précision > rappel sur les types ambigus : on préfère ne pas sur-tokeniser le
bruit. Le matching le plus spécifique d'abord (CIDR avant IP nue) évite qu'un
sous-réseau ré-émette son IP.

Une variante spaCy (``NERExtractor``) reste disponible via l'extra [ner] pour le
NL riche, mais n'est pas câblée par défaut.
"""

from __future__ import annotations

import re

from core.tokens.vault import ExtractFn

_IPV4 = r"(?:\d{1,3}\.){3}\d{1,3}"
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("IP_SUBNET", re.compile(rf"\b{_IPV4}/\d{{1,2}}\b")),
    ("IP_ADDRESS", re.compile(rf"\b{_IPV4}\b")),
    ("MAC_ADDRESS", re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")),
    ("CVE", re.compile(r"\bCVE-\d{4}-\d{4,7}\b")),
    ("HASH", re.compile(r"\b(?:[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64})\b")),
    ("HOSTNAME", re.compile(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b")),
    ("PORT_NUMBER", re.compile(r"(?<=:)\d{2,5}\b")),
]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def build_regex_extractor() -> ExtractFn:
    """Renvoie un extracteur pur : texte → {label: [valeurs uniques, ordre stable]}."""

    def _extract(text: str) -> dict[str, list[str]]:
        # On masque au fur et à mesure les segments déjà capturés par un label plus
        # spécifique, pour qu'un CIDR ne soit pas ré-émis comme IP nue ni un FQDN
        # comme rien d'autre.
        remaining = text
        result: dict[str, list[str]] = {}
        for label, pattern in _PATTERNS:
            found = pattern.findall(remaining)
            result[label] = _dedupe(found)
            if found:
                remaining = pattern.sub(" ", remaining)
        return result

    return _extract
```

Note : l'ordre de `_PATTERNS` est la priorité. `IP_SUBNET` avant `IP_ADDRESS` (le CIDR est masqué avant de chercher l'IP nue) ; `HOSTNAME` après `IP`/`MAC`/`CVE`/`HASH` pour ne pas capturer un fragment d'IP ; `PORT_NUMBER` exige un `:` devant (lookbehind) pour ne pas matcher des nombres isolés.

- [ ] **Step 4 : Lancer, vérifier le succès + typage + lint**

Run: `.venv/bin/pytest tests/coordinator/test_extractor.py -q && .venv/bin/mypy coordinator/extractor.py && .venv/bin/ruff check coordinator/extractor.py tests/coordinator/test_extractor.py`
Expected: PASS ; mypy Success ; ruff clean. Si un test échoue sur un motif (ex. le hostname capture une IP masquée), ajuster l'ordre/les regex — ne pas affaiblir un test.

- [ ] **Step 5 : Étendre mypy + commit**

Ajouter `"coordinator/extractor.py"` à `[tool.mypy].files`. Puis :
```bash
.venv/bin/mypy
git add coordinator/extractor.py tests/coordinator/test_extractor.py pyproject.toml
git commit -m "feat(coordinator/extractor): extracteur PII regex deterministe"
```

---

### Task 3 : `coordinator/config.py` — chargement de config fail-closed

**Files:**
- Create: `coordinator/config.py`
- Test: `tests/coordinator/test_config.py`
- Modify: `pyproject.toml` (`[tool.mypy].files` += `coordinator/config.py`)

**Interfaces:**
- Consumes: `core.auth.api_key.load_auth_secret` / `AuthNotConfigured` (A) ; `coordinator.session.load_session_key` / `SessionKeyNotConfigured` (C).
- Produces:
  - `coordinator/config.py::ConfigError(Exception)`.
  - `@dataclass(frozen=True) CoordinatorConfig` : champs `auth_secret: str`, `session_key: bytes`, `policy_file: Path`, `audit_file: Path`, `session_dir: Path`, `host: str`, `port: int`, `agent_server_url: str`, `agent_server_sock: str`, `agent_server_key: str`.
  - `load_config(env: Mapping[str, str]) -> CoordinatorConfig` — fail-closed sur les obligatoires.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/coordinator/test_config.py
from pathlib import Path
import pytest
from coordinator.config import load_config, ConfigError
from core.auth.api_key import AuthNotConfigured
from coordinator.session import SessionKeyNotConfigured


def _base_env(**over):
    env = {
        "COORDINATOR_API_KEY": "secret",
        "COORDINATOR_SESSION_KEY": "k" * 44,
        "COORDINATOR_POLICY_FILE": "/tmp/policy.yml",
    }
    env.update(over)
    return env


def test_loads_with_defaults():
    cfg = load_config(_base_env())
    assert cfg.auth_secret == "secret"
    assert cfg.policy_file == Path("/tmp/policy.yml")
    assert cfg.audit_file == Path("audit.jsonl")
    assert cfg.session_dir == Path("sessions")
    assert cfg.host == "127.0.0.1" and cfg.port == 8080
    assert cfg.agent_server_url == "http://localhost:3000"


def test_missing_auth_key_fails_closed():
    env = _base_env()
    del env["COORDINATOR_API_KEY"]
    with pytest.raises(AuthNotConfigured):
        load_config(env)


def test_missing_session_key_fails_closed():
    env = _base_env()
    del env["COORDINATOR_SESSION_KEY"]
    with pytest.raises(SessionKeyNotConfigured):
        load_config(env)


def test_missing_policy_file_fails_closed():
    env = _base_env()
    del env["COORDINATOR_POLICY_FILE"]
    with pytest.raises(ConfigError):
        load_config(env)


def test_overrides_applied():
    cfg = load_config(_base_env(COORDINATOR_PORT="9000", AGENT_SERVER_SOCK="/run/a.sock"))
    assert cfg.port == 9000
    assert cfg.agent_server_sock == "/run/a.sock"
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/coordinator/test_config.py -q`
Expected: FAIL (`No module named 'coordinator.config'`).

- [ ] **Step 3 : Implémenter `coordinator/config.py`**

```python
"""Chargement de la configuration du coordinateur — fail-closed sur les obligatoires.

Les secrets/chemins/endpoints viennent de l'environnement ; les règles de
politique d'un fichier YAML séparé (voir load_policy). Un obligatoire manquant
lève une erreur claire au démarrage plutôt qu'un crash opaque.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from core.auth.api_key import load_auth_secret
from coordinator.session import load_session_key


class ConfigError(Exception):
    """Configuration incomplète — le coordinateur ne doit pas démarrer."""


@dataclass(frozen=True)
class CoordinatorConfig:
    auth_secret: str
    session_key: bytes
    policy_file: Path
    audit_file: Path
    session_dir: Path
    host: str
    port: int
    agent_server_url: str
    agent_server_sock: str
    agent_server_key: str


def load_config(env: Mapping[str, str]) -> CoordinatorConfig:
    auth_secret = load_auth_secret(env, "COORDINATOR_API_KEY")       # lève AuthNotConfigured
    session_key = load_session_key(env, "COORDINATOR_SESSION_KEY")   # lève SessionKeyNotConfigured
    policy_file = env.get("COORDINATOR_POLICY_FILE", "")
    if not policy_file:
        raise ConfigError("COORDINATOR_POLICY_FILE absent : chemin du policy.yml requis")
    return CoordinatorConfig(
        auth_secret=auth_secret,
        session_key=session_key,
        policy_file=Path(policy_file),
        audit_file=Path(env.get("COORDINATOR_AUDIT_FILE", "audit.jsonl")),
        session_dir=Path(env.get("COORDINATOR_SESSION_DIR", "sessions")),
        host=env.get("COORDINATOR_HOST", "127.0.0.1"),
        port=int(env.get("COORDINATOR_PORT", "8080")),
        agent_server_url=env.get("AGENT_SERVER_URL", "http://localhost:3000"),
        agent_server_sock=env.get("AGENT_SERVER_SOCK", ""),
        agent_server_key=env.get("AGENT_SERVER_KEY", ""),
    )
```

- [ ] **Step 4 : Lancer, succès + typage + lint**

Run: `.venv/bin/pytest tests/coordinator/test_config.py -q && .venv/bin/mypy coordinator/config.py && .venv/bin/ruff check coordinator/config.py tests/coordinator/test_config.py`
Expected: PASS ; mypy Success ; ruff clean.

- [ ] **Step 5 : Étendre mypy + commit**

Ajouter `"coordinator/config.py"` à `[tool.mypy].files`. Puis :
```bash
.venv/bin/mypy
git add coordinator/config.py tests/coordinator/test_config.py pyproject.toml
git commit -m "feat(coordinator/config): chargement de config fail-closed"
```

---

### Task 4 : Dette `rule_reason` — préserver la règle à l'audit post-approbation

**Files:**
- Modify: `core/audit/sink.py` (`entry_from_verdict` : param `rule_reason`)
- Modify: `coordinator/session.py` (`SessionState` : champ `rule_reason`)
- Modify: `coordinator/loop.py` (suspend enregistre, resume/reject réinjectent)
- Test: `tests/coordinator/test_loop_rule_reason.py`

**Interfaces:**
- Consumes: `core.audit.sink.entry_from_verdict`, `coordinator.session.SessionState`, `coordinator.loop.GatedLoop`.
- Produces: `entry_from_verdict(verdict, event, actor="coordinator", rule_reason: str | None = None)` — si `rule_reason` fourni, il prime sur `verdict.matched_rule`. `SessionState.rule_reason: str | None = None`.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/coordinator/test_loop_rule_reason.py
import itertools
import pytest
from coordinator.loop import GatedLoop, Suspended, Completed
from coordinator.proposer import Act, Finish
from coordinator.session import MemorySessionStore
from core.approval.store import ApprovalStore
from core.audit.sink import MemoryAuditSink
from core.policy.catalog import Capability, CapabilityCatalog
from core.policy.models import Intention, Match, Rule


class _Proposer:
    def __init__(self, seq): self._it = iter(seq)
    async def propose(self, request_tokens, history): return next(self._it)


@pytest.mark.asyncio
async def test_audit_post_approval_carries_rule_reason():
    proposer = _Proposer([
        Act(intention=Intention(capability="crowdsec.ban_ip", args={"ip": "IP_1"})),
        Finish(summary="banni"),
    ])
    policy = [Rule(match=Match(capability="crowdsec.ban_ip"), effect="approve",
                   reason="ban requiert validation")]
    sink = MemoryAuditSink()
    approvals = ApprovalStore()

    async def _call(cap, args): return {"status": "banned"}

    loop = GatedLoop(
        proposer=proposer,
        catalog=CapabilityCatalog([Capability(name="crowdsec.ban_ip", required_args=["ip"])]),
        policy=policy, sink=sink, approvals=approvals, sessions=MemorySessionStore(),
        call=_call, extract=lambda t: {"IP": ["203.0.113.9"]} if "203" in t else {},
        clock=lambda: 0.0, id_factory=(lambda c=itertools.count(1): f"a{next(c)}"),
    )
    res = await loop.handle("banni 203.0.113.9")
    assert isinstance(res, Suspended)
    approvals.approve(res.approval_id, approvals.get(res.approval_id).intention_hash)
    res2 = await loop.resume(res.approval_id)
    assert isinstance(res2, Completed)
    post = [e for e in sink.entries if e.event == "executed_after_approval"]
    assert post and post[0].rule_reason == "ban requiert validation"
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/coordinator/test_loop_rule_reason.py -q`
Expected: FAIL (l'entrée `executed_after_approval` a `rule_reason=None`).

- [ ] **Step 3 : Ajouter le param à `entry_from_verdict`**

Dans `core/audit/sink.py`, remplacer la fonction `entry_from_verdict` :

```python
def entry_from_verdict(
    verdict: Verdict, event: str, actor: str = "coordinator", rule_reason: str | None = None
) -> AuditEntry:
    reason = rule_reason if rule_reason is not None else (
        verdict.matched_rule.reason if verdict.matched_rule else None
    )
    return AuditEntry(
        event=event,
        capability=verdict.intention.capability,
        effect=verdict.effect,
        rule_reason=reason,
        args=verdict.intention.args,
        actor=actor,
    )
```

- [ ] **Step 4 : Ajouter le champ à `SessionState`**

Dans `coordinator/session.py`, classe `SessionState`, ajouter après `results` :

```python
    rule_reason: str | None = None
```

- [ ] **Step 5 : Câbler dans `coordinator/loop.py`**

1. Au **suspend** (dans `_run`, la branche `approve`), enregistrer la raison de la règle dans la session. Remplacer le bloc `self._sessions.save(SessionState(...))` par :

```python
                self._sessions.save(SessionState(
                    id=sid, request_tokens=request_tokens, vault_snapshot=vault.snapshot(),
                    history=history, step=step, expires_at=self._clock() + self._ttl,
                    results=results,
                    rule_reason=(verdict.matched_rule.reason if verdict.matched_rule else None),
                ))
```

2. Au **resume**, passer `rule_reason` de la session à l'audit. La `session` est déjà chargée en tête de `resume` ; remplacer la ligne d'audit `executed_after_approval` :

```python
        self._sink.write(entry_from_verdict(
            verdict, event="executed_after_approval", rule_reason=session.rule_reason
        ))
```

Et pour l'audit `resume_refuse` (avant l'exécution, la session est disponible) :

```python
            self._sink.write(entry_from_verdict(
                verdict, event="resume_refuse", rule_reason=session.rule_reason
            ))
```

3. Au **reject**, charger la session pour récupérer `rule_reason` (graceful si absente). Remplacer le corps de `reject` :

```python
    def reject(self, approval_id: str) -> LoopResult:
        """Rejette une approbation en attente : purge la session, aucune exécution."""
        approval = self._approvals.get(approval_id)
        if approval is None:
            return Failed(reason="approbation inconnue")
        session = self._sessions.get(approval_id, now=self._clock())
        rule_reason = session.rule_reason if session is not None else None
        self._approvals.reject(approval_id)
        self._sessions.delete(approval_id)
        verdict = Verdict(effect="approve", matched_rule=None, intention=approval.intention)
        self._sink.write(entry_from_verdict(verdict, event="rejected", rule_reason=rule_reason))
        return Denied(reason="rejeté par l'opérateur")
```

- [ ] **Step 6 : Lancer le nouveau test + non-régression boucle/audit**

Run: `.venv/bin/pytest tests/coordinator/test_loop_rule_reason.py tests/coordinator/test_loop.py tests/core/test_audit.py -q && .venv/bin/mypy coordinator/loop.py coordinator/session.py core/audit/sink.py && .venv/bin/ruff check coordinator/loop.py coordinator/session.py core/audit/sink.py tests/coordinator/test_loop_rule_reason.py`
Expected: PASS (les tests boucle B et audit A restent verts) ; mypy Success ; ruff clean.

- [ ] **Step 7 : Commit**

```bash
git add core/audit/sink.py coordinator/session.py coordinator/loop.py tests/coordinator/test_loop_rule_reason.py
git commit -m "fix(coordinator/loop): preserver rule_reason a l audit post-approbation"
```

---

### Task 5 : Dette no-silent-simulation — propager les erreurs d'inférence

**Files:**
- Modify: `agents/base.py` (`_infer_with_vllm`, `_infer_with_lora` : retirer le fallback simulation silencieux) ; `agents/crowdsec_agent.py` (`_infer_with_ollama` override)
- Test: `tests/agents/test_no_silent_simulation.py`

**Interfaces:**
- Consumes: `agents.base.ToolAgent`.
- Produces: sur erreur runtime, `_infer_with_vllm`/`_infer_with_ollama`/`_infer_with_lora` **propagent l'exception** (attrapée en amont par `execute()` → `ToolResult(success=False)`) au lieu de retomber en `_infer_with_simulation`. `_infer_with_simulation` reste défini (utilisable en test/dev) mais n'est plus un fallback silencieux de ces chemins.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/agents/test_no_silent_simulation.py
import pytest
from typing import Dict
from agents.base import ToolAgent


class _Agent(ToolAgent):
    def __init__(self, **kw):
        super().__init__(tool_name="t", model_path=None, **kw)

    def _register_functions(self):
        return {"get_metrics": self._get_metrics}

    async def _get_metrics(self):
        return {"ok": True}


class _BrokenOllama:
    def chat(self, *a, **k):
        raise RuntimeError("ollama indisponible")


@pytest.mark.asyncio
async def test_ollama_error_does_not_silently_simulate():
    # execute() attrape l'exception -> ToolResult échec, PAS un résultat simulé.
    agent = _Agent(ollama_config={"model": "m", "url": "http://x"})
    agent.ollama_client = _BrokenOllama()
    res = await agent.execute("montre les métriques")
    assert res.success is False
    assert res.function != "get_metrics"  # rien n'a été « deviné » puis exécuté
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/agents/test_no_silent_simulation.py -q`
Expected: FAIL (le fallback simulation « devine » une fonction et `execute` peut réussir).

- [ ] **Step 3 : Retirer le fallback simulation silencieux**

Règle générale : dans **chacune** des méthodes `_infer_with_vllm`, `_infer_with_ollama`, `_infer_with_lora` de `agents/base.py`, repérer tout bloc `except ...:` se terminant par `return await self._infer_with_simulation(user_request)` et remplacer ce `return await self._infer_with_simulation(...)` par `raise` (en gardant le `logger.error(...)` qui précède). Si une méthode n'a pas ce fallback, ne rien y changer. Exemple pour `_infer_with_lora` :

```python
        except Exception as e:
            logger.error(f"Erreur lors de l'inférence LoRA: {e}")
            raise
```

Le test utilise un `ToolAgent` de base avec `ollama_client` → c'est donc `agents/base.py::_infer_with_ollama` qui doit propager (ne pas oublier cette méthode-là dans base.py, en plus de l'override crowdsec ci-dessous).

Dans `agents/crowdsec_agent.py`, méthode `_infer_with_ollama` (override), remplacer :

```python
        except Exception as e:
            logger.error(f"Erreur inférence Ollama: {e}")
            return await self._infer_with_simulation(user_request)
```

par :

```python
        except Exception as e:
            logger.error(f"Erreur inférence Ollama: {e}")
            raise
```

Ne PAS supprimer la méthode `_infer_with_simulation` elle-même (elle reste disponible pour un usage explicite dev/CI).

- [ ] **Step 4 : Lancer le test + non-régression agents**

Run: `.venv/bin/pytest tests/agents/test_no_silent_simulation.py tests/agents -q`
Expected: PASS (la suite agents reste verte).

- [ ] **Step 5 : Commit**

```bash
git add agents/base.py agents/crowdsec_agent.py tests/agents/test_no_silent_simulation.py
git commit -m "fix(agents): propager les erreurs d inference au lieu de simuler en silence"
```

---

### Task 6 : Câblage env→agent (serveur d'agents)

**Files:**
- Create: `agents/infer_wiring.py`
- Modify: `server.py` (lifespan : construire l'`OpenAICompatClient` et injecter dans les agents)
- Test: `tests/agents/test_infer_wiring.py`
- Modify: `pyproject.toml` (`[tool.mypy].files` += `agents/infer_wiring.py`)

**Interfaces:**
- Consumes: `clients.openai_compat_client.OpenAICompatClient` (C).
- Produces:
  - `agents/infer_wiring.py::resolve_lora_models(env: Mapping[str, str]) -> dict[str, str]` — mappe nom d'agent → nom de LoRA depuis `<AGENT>_LORA_MODEL` (prioritaire) et `AGENT_LORA_MODELS="crowdsec=crowdsec-lora,opnsense=opnsense-lora"`.
  - `agents/infer_wiring.py::build_infer_client(env) -> OpenAICompatClient | None` — construit le client si `AGENT_INFER_BASE_URL` défini, sinon `None`.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/agents/test_infer_wiring.py
from agents.infer_wiring import resolve_lora_models, build_infer_client
from clients.openai_compat_client import OpenAICompatClient


def test_resolve_from_per_agent_var():
    env = {"CROWDSEC_LORA_MODEL": "crowdsec-lora"}
    assert resolve_lora_models(env)["crowdsec"] == "crowdsec-lora"


def test_resolve_from_global_map():
    env = {"AGENT_LORA_MODELS": "crowdsec=cs-lora,opnsense=op-lora"}
    m = resolve_lora_models(env)
    assert m["crowdsec"] == "cs-lora" and m["opnsense"] == "op-lora"


def test_per_agent_overrides_global():
    env = {"AGENT_LORA_MODELS": "crowdsec=global", "CROWDSEC_LORA_MODEL": "specifique"}
    assert resolve_lora_models(env)["crowdsec"] == "specifique"


def test_build_client_none_without_base_url():
    assert build_infer_client({}) is None


def test_build_client_when_base_url_set():
    client = build_infer_client({"AGENT_INFER_BASE_URL": "http://x/v1", "AGENT_INFER_API_KEY": "k"})
    assert isinstance(client, OpenAICompatClient)
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/agents/test_infer_wiring.py -q`
Expected: FAIL (`No module named 'agents.infer_wiring'`).

- [ ] **Step 3 : Implémenter `agents/infer_wiring.py`**

```python
"""Câblage du backend d'inférence NL des agents depuis l'environnement.

Construit un OpenAICompatClient partagé (si AGENT_INFER_BASE_URL est défini) et
résout le nom de LoRA par agent. Le serveur d'agents injecte ces valeurs dans
chaque ToolAgent (params openai_client/lora_model livrés en C).
"""

from __future__ import annotations

from collections.abc import Mapping

from clients.openai_compat_client import OpenAICompatClient


def resolve_lora_models(env: Mapping[str, str]) -> dict[str, str]:
    """Mappe agent → nom de LoRA. `<AGENT>_LORA_MODEL` prime sur `AGENT_LORA_MODELS`."""
    models: dict[str, str] = {}
    global_map = env.get("AGENT_LORA_MODELS", "")
    for pair in global_map.split(","):
        if "=" in pair:
            name, _, model = pair.partition("=")
            name, model = name.strip(), model.strip()
            if name and model:
                models[name] = model
    for key, value in env.items():
        if key.endswith("_LORA_MODEL") and value:
            agent = key[: -len("_LORA_MODEL")].lower()
            models[agent] = value
    return models


def build_infer_client(env: Mapping[str, str]) -> OpenAICompatClient | None:
    """Construit le client d'inférence partagé si un endpoint est configuré, sinon None."""
    base_url = env.get("AGENT_INFER_BASE_URL", "")
    if not base_url:
        return None
    return OpenAICompatClient(base_url=base_url, api_key=env.get("AGENT_INFER_API_KEY", ""))
```

- [ ] **Step 4 : Câbler dans `server.py`**

Dans le `lifespan` de `server.py`, avant la construction des agents, ajouter :

```python
    from agents.infer_wiring import build_infer_client, resolve_lora_models
    _infer_client = build_infer_client(os.environ)
    _lora_models = resolve_lora_models(os.environ)
```

Puis, à chaque construction d'agent (`OPNsenseAgent(...)`, `WireGuardAgent(...)`, `CrowdSecAgent(...)`), ajouter les deux paramètres (les agents acceptent déjà `openai_client`/`lora_model` — livrés en C). Exemple pour CrowdSec :

```python
    agents["crowdsec"] = CrowdSecAgent(
        model_path=None,
        api_config=crowdsec_config,
        ollama_config=ollama_config,
        vllm_client=vllm_client,
        openai_client=_infer_client,
        lora_model=_lora_models.get("crowdsec", ""),
    )
```

(Idem `opnsense`/`wireguard` avec `_lora_models.get("opnsense"/"wireguard", "")`.) Dans le **shutdown** du lifespan, fermer le client s'il existe :

```python
    if _infer_client is not None:
        await _infer_client.aclose()
```

Vérifier que `OPNsenseAgent`/`WireGuardAgent.__init__` acceptent bien `openai_client`/`lora_model` (hérités de `ToolAgent`) ; s'ils redéfinissent `__init__` sans passer `**kwargs` au `super().__init__`, ajouter le passage des deux paramètres. Si un agent ne les accepte pas, l'ajouter de la même façon que la signature de `ToolAgent`.

- [ ] **Step 5 : Lancer les tests**

Run: `.venv/bin/pytest tests/agents/test_infer_wiring.py -q && .venv/bin/mypy agents/infer_wiring.py && .venv/bin/ruff check agents/infer_wiring.py tests/agents/test_infer_wiring.py`
Expected: PASS ; mypy Success ; ruff clean. Puis `.venv/bin/pytest tests/agents -q` (non-régression).

- [ ] **Step 6 : Étendre mypy + commit**

Ajouter `"agents/infer_wiring.py"` à `[tool.mypy].files`. Puis :
```bash
.venv/bin/mypy
git add agents/infer_wiring.py server.py tests/agents/test_infer_wiring.py pyproject.toml
git commit -m "feat(agents): cablage env vers backend d inference OpenAI-compatible"
```

---

### Task 7 : Assemblage du coordinateur (`create_default_app`) + refactor `build_app`

**Files:**
- Create: `coordinator/assembly.py`
- Modify: `coordinator/app.py` (refactor `build_app` → routes via `app.state.loop` ; `create_default_app` + lifespan)
- Test: `tests/coordinator/test_assembly.py`
- Modify: `pyproject.toml` (`[tool.mypy].files` += `coordinator/assembly.py`)

**Interfaces:**
- Consumes: `coordinator.config.load_config`/`CoordinatorConfig`, `coordinator.catalog_builder.build_catalog`, `core.policy.loading.load_policy`, `coordinator.proposer.LlmProposer`, `coordinator.llm.coordinator_llm.CoordinatorLLM`, `coordinator.agent_call.make_agent_call`, `coordinator.session.EncryptedFileSessionStore`, `core.approval.store.ApprovalStore`, `core.audit.file_sink.FileAuditSink`, `coordinator.extractor.build_regex_extractor`, `coordinator.loop.GatedLoop`, `coordinator.app.build_app`.
- Produces:
  - `coordinator/assembly.py::AssemblyError(Exception)`.
  - `coordinator/assembly.py::discover_agents(caps: dict) -> dict[str, list[dict]]` — `{a["name"]: a["functions"] for a in caps["agents"]}`.
  - `coordinator/assembly.py::async assemble_loop(config, agent_client, llm) -> GatedLoop` — awaits `agent_client.get_capabilities()`, découvre les agents, build_catalog + conformance, charge la politique, construit la boucle. `AssemblyError` si aucun agent découvert.
  - `coordinator/app.py::create_default_app() -> FastAPI` — app avec lifespan qui assemble la boucle dans `app.state.loop`.
  - `build_app` reste `build_app(*, loop, auth_secret) -> FastAPI` mais les routes lisent `request.app.state.loop`.

- [ ] **Step 1 : Écrire le test qui échoue (assemblage avec faux client/LLM)**

```python
# tests/coordinator/test_assembly.py
import json
from pathlib import Path
import pytest

from coordinator.assembly import assemble_loop, discover_agents, AssemblyError
from coordinator.config import CoordinatorConfig
from coordinator.loop import GatedLoop, Suspended, Completed
from cryptography.fernet import Fernet
from agents.crowdsec_agent import CrowdSecAgent

# IMPORTANT : les capacités live doivent correspondre au manifeste crowdsec.yml
# (15 fonctions) sinon build_catalog->check_conformance (sous-projet C) refuse.
# On les prend donc de l'agent réel (mode simulation, sans LAPI).
_CROWDSEC_FUNCS = CrowdSecAgent(model_path=None).get_capabilities()
_CAPS = {"agents": [{"name": "crowdsec", "tool_name": "crowdsec", "functions": _CROWDSEC_FUNCS}]}


class _FakeClient:
    async def get_capabilities(self): return _CAPS
    async def execute_structured(self, function, args): return {"status": "banned", "fn": function}


class _FakeLLM:
    def __init__(self, replies): self._it = iter(replies)
    async def chat(self, messages, max_tokens=1024): return next(self._it)


def _cfg(tmp_path: Path, policy_text: str) -> CoordinatorConfig:
    pol = tmp_path / "policy.yml"; pol.write_text(policy_text, encoding="utf-8")
    return CoordinatorConfig(
        auth_secret="s", session_key=Fernet.generate_key(), policy_file=pol,
        audit_file=tmp_path / "audit.jsonl", session_dir=tmp_path / "sessions",
        host="127.0.0.1", port=8080, agent_server_url="http://x", agent_server_sock="",
        agent_server_key="",
    )


def test_discover_agents():
    names = {f["name"] for f in discover_agents(_CAPS)["crowdsec"]}
    assert "ban_ip" in names and "get_metrics" in names


@pytest.mark.asyncio
async def test_assemble_loop_builds_a_working_loop(tmp_path: Path):
    policy = "rules:\n  - match: {capability: 'crowdsec.ban_ip'}\n    effect: approve\n    reason: r\n"
    cfg = _cfg(tmp_path, policy)
    llm = _FakeLLM([
        json.dumps({"action": {"capability": "crowdsec.ban_ip", "args": {"ip": "IP_1"}}}),
        json.dumps({"final": "ok"}),
    ])
    loop = await assemble_loop(cfg, _FakeClient(), llm)
    assert isinstance(loop, GatedLoop)
    res = await loop.handle("banni 203.0.113.9")
    assert isinstance(res, Suspended)
    assert cfg.audit_file.exists()  # FileAuditSink a écrit


@pytest.mark.asyncio
async def test_invalid_policy_refuses(tmp_path: Path):
    # glob ne couvrant aucune capacité connue -> load_policy lève -> assemble échoue
    cfg = _cfg(tmp_path, "rules:\n  - match: {capability: 'inconnu.*'}\n    effect: allow\n")
    with pytest.raises(Exception):
        await assemble_loop(cfg, _FakeClient(), _FakeLLM([]))


@pytest.mark.asyncio
async def test_no_agents_discovered_refuses(tmp_path: Path):
    class _Empty:
        async def get_capabilities(self): return {"agents": []}
        async def execute_structured(self, function, args): return {}
    cfg = _cfg(tmp_path, "rules: []\n")
    with pytest.raises(AssemblyError):
        await assemble_loop(cfg, _Empty(), _FakeLLM([]))
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/coordinator/test_assembly.py -q`
Expected: FAIL (`No module named 'coordinator.assembly'`).

- [ ] **Step 3 : Implémenter `coordinator/assembly.py`**

```python
"""Assemblage de la boucle du coordinateur à partir de la config et d'un client d'agent.

Sépare la logique de câblage (testable avec des doubles) de l'app FastAPI. Le
catalogue est découvert au démarrage depuis le `/capabilities` live du serveur
d'agents ; la conformance manifeste↔live (sous-projet C) s'applique. Politique
invalide ou aucun agent découvert → échec de démarrage fail-closed.
"""

from __future__ import annotations

import time
from typing import Any, Protocol
from uuid import uuid4

import yaml

from coordinator.agent_call import make_agent_call
from coordinator.config import CoordinatorConfig
from coordinator.catalog_builder import build_catalog
from coordinator.extractor import build_regex_extractor
from coordinator.loop import GatedLoop
from coordinator.proposer import ChatLLM, LlmProposer
from coordinator.session import EncryptedFileSessionStore
from core.approval.store import ApprovalStore
from core.audit.file_sink import FileAuditSink
from core.policy.loading import load_policy


class AssemblyError(Exception):
    """L'assemblage runtime a échoué (aucun agent, config incohérente)."""


class AgentClientLike(Protocol):
    async def get_capabilities(self) -> dict[str, Any]: ...
    async def execute_structured(self, function: str, args: dict[str, Any]) -> dict[str, Any]: ...


def discover_agents(caps: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Extrait {nom_agent: [capacités]} de la réponse /capabilities du serveur d'agents."""
    return {a["name"]: a["functions"] for a in caps.get("agents", [])}


async def assemble_loop(
    config: CoordinatorConfig, agent_client: AgentClientLike, llm: ChatLLM
) -> GatedLoop:
    caps = await agent_client.get_capabilities()
    live = discover_agents(caps)
    if not live:
        raise AssemblyError("aucun agent découvert sur le serveur d'agents")
    catalog = await build_catalog(list(live), live)  # conformance C ; drift → refus
    raw = yaml.safe_load(config.policy_file.read_text(encoding="utf-8")) or {}
    policy = load_policy(raw.get("rules", []), catalog)  # fail-closed sur règle/glob invalide
    return GatedLoop(
        proposer=LlmProposer(llm=llm, catalog=catalog),
        catalog=catalog,
        policy=policy,
        sink=FileAuditSink(config.audit_file),
        approvals=ApprovalStore(),
        sessions=EncryptedFileSessionStore(config.session_dir, config.session_key),
        call=make_agent_call({name: agent_client for name in live}),
        extract=build_regex_extractor(),
        clock=time.time,
        id_factory=lambda: uuid4().hex,
    )
```

- [ ] **Step 4 : Lancer, vérifier le succès de l'assemblage**

Run: `.venv/bin/pytest tests/coordinator/test_assembly.py -q`
Expected: PASS.

- [ ] **Step 5 : Écrire le test du refactor `build_app` + `create_default_app`**

```python
# ajouter à tests/coordinator/test_app.py (nouveaux tests, ne pas modifier les existants)
def test_build_app_reads_loop_from_state():
    # les routes existantes doivent continuer à marcher via app.state.loop.
    # Réutilise les helpers _loop / _client et l'import Finish déjà présents dans ce fichier.
    from coordinator.proposer import Act, Finish
    from core.policy.models import Intention, Match, Rule
    seq = [Act(intention=Intention(capability="crowdsec.get_metrics", args={})), Finish(summary="fini")]
    policy = [Rule(match=Match(capability="crowdsec.get_metrics"), effect="allow")]
    r = _client(_loop(seq, policy)).post(
        "/coordinator/execute", headers={"X-API-Key": "secret"}, json={"request": "métriques"}
    )
    assert r.status_code == 200 and r.json()["status"] == "completed"
```

```python
# tests/coordinator/test_create_default_app.py
import importlib
import pytest
from fastapi.testclient import TestClient


def test_create_default_app_refuses_without_secrets(monkeypatch):
    monkeypatch.delenv("COORDINATOR_API_KEY", raising=False)
    from coordinator.app import create_default_app
    # l'auth secret est requis pour construire l'app (fail-closed)
    with pytest.raises(Exception):
        create_default_app()


def test_import_coordinator_app_stays_light():
    import subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    code = ("import sys, coordinator.app; "
            "assert not ({'torch','vllm','unsloth'} & set(sys.modules))")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(root), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
```

- [ ] **Step 6 : Refactorer `coordinator/app.py`**

Remplacer le corps de `build_app` pour que les routes lisent `request.app.state.loop` (via un helper partagé), et ajouter `create_default_app` + son lifespan :

```python
from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel

from coordinator.loop import Completed, Denied, Failed, GatedLoop, LoopResult, Suspended
from core.auth.api_key import load_auth_secret, make_auth_dependency


class ExecuteRequest(BaseModel):
    request: str


def _serialize(result: LoopResult) -> dict[str, Any]:
    if isinstance(result, Completed):
        return {"status": "completed", "summary": result.summary, "results": result.results}
    if isinstance(result, Suspended):
        return {"status": "pending_approval", "approval_id": result.approval_id}
    if isinstance(result, Denied):
        return {"status": "denied", "reason": result.reason}
    if isinstance(result, Failed):
        return {"status": "failed", "reason": result.reason}
    raise TypeError(f"LoopResult non géré: {type(result)!r}")


def _register_routes(app: FastAPI, auth_secret: str) -> None:
    require_auth = make_auth_dependency(auth_secret)

    @app.get("/coordinator/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/coordinator/execute", dependencies=[Depends(require_auth)])
    async def execute(req: ExecuteRequest, request: Request) -> dict[str, Any]:
        return _serialize(await request.app.state.loop.handle(req.request))

    @app.post("/coordinator/resume/{approval_id}", dependencies=[Depends(require_auth)])
    async def resume(approval_id: str, request: Request) -> dict[str, Any]:
        return _serialize(await request.app.state.loop.resume(approval_id))

    @app.post("/coordinator/reject/{approval_id}", dependencies=[Depends(require_auth)])
    async def reject(approval_id: str, request: Request) -> dict[str, Any]:
        return _serialize(request.app.state.loop.reject(approval_id))


def build_app(*, loop: GatedLoop, auth_secret: str) -> FastAPI:
    app = FastAPI(title="Cyber Coordinator", version="2.0")
    app.state.loop = loop
    _register_routes(app, auth_secret)
    return app
```

Puis ajouter `create_default_app` (assemblage réseau dans le lifespan) :

```python
from contextlib import asynccontextmanager

from coordinator.assembly import assemble_loop
from coordinator.clients.tool_agent_client import ToolAgentClient
from coordinator.config import load_config
from coordinator.llm.coordinator_llm import CoordinatorLLM


def create_default_app() -> FastAPI:
    """Assemble l'app runtime depuis l'environnement (fail-closed sur secrets)."""
    config = load_config(os.environ)  # lève si secrets/chemin manquants (au démarrage)

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        client = ToolAgentClient(
            base_url=config.agent_server_url,
            api_key=config.agent_server_key,
            socket_path=config.agent_server_sock,
        )
        await client.__aenter__()
        llm = CoordinatorLLM()
        await llm.init()
        try:
            app.state.loop = await assemble_loop(config, client, llm)
            yield
        finally:
            await client.__aexit__(None, None, None)
            await llm.shutdown()

    app = FastAPI(title="Cyber Coordinator", version="2.0", lifespan=_lifespan)
    _register_routes(app, config.auth_secret)
    return app


def run() -> None:
    """Point d'entrée console : lance uvicorn sur l'app assemblée."""
    import uvicorn

    config = load_config(os.environ)
    uvicorn.run(create_default_app(), host=config.host, port=config.port)
```

- [ ] **Step 7 : Lancer tous les tests coordinateur (dont B) + garde-fou d'import**

Run: `.venv/bin/pytest tests/coordinator -q && .venv/bin/pytest tests/test_portability.py -q && .venv/bin/mypy coordinator/assembly.py coordinator/app.py && .venv/bin/ruff check coordinator/assembly.py coordinator/app.py tests/coordinator/test_assembly.py tests/coordinator/test_create_default_app.py`
Expected: PASS (les tests B de `test_app.py` restent verts avec le refactor `app.state`) ; garde-fou d'import léger vert ; mypy Success ; ruff clean.

- [ ] **Step 8 : Étendre mypy + commit**

Ajouter `"coordinator/assembly.py"` à `[tool.mypy].files`. Puis :
```bash
.venv/bin/mypy
git add coordinator/assembly.py coordinator/app.py tests/coordinator/test_assembly.py tests/coordinator/test_create_default_app.py tests/coordinator/test_app.py pyproject.toml
git commit -m "feat(coordinator): assemblage runtime create_default_app via lifespan"
```

---

### Task 8 : Point d'entrée console, `policy.example.yml`, README

**Files:**
- Modify: `pyproject.toml` (`[project.scripts]`, dep core `uvicorn`)
- Create: `policy.example.yml`
- Modify: `README.md` (section « Lancer le coordinateur »)
- Test: `tests/test_entrypoint.py`

**Interfaces:**
- Consumes: `coordinator.app:run` (Task 7).
- Produces: console script `cyber-coordinator = "coordinator.app:run"` ; `policy.example.yml` valide.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_entrypoint.py
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _cfg() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_console_script_declared():
    scripts = _cfg()["project"].get("scripts", {})
    assert scripts.get("cyber-coordinator") == "coordinator.app:run"


def test_uvicorn_is_core_dep():
    deps = " ".join(_cfg()["project"]["dependencies"]).lower()
    assert "uvicorn" in deps


def test_run_is_importable():
    from coordinator.app import run
    assert callable(run)


def test_example_policy_is_valid_yaml_with_rules():
    import yaml
    data = yaml.safe_load((_ROOT / "policy.example.yml").read_text(encoding="utf-8"))
    assert isinstance(data.get("rules"), list) and data["rules"]
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_entrypoint.py -q`
Expected: FAIL (script non déclaré, `policy.example.yml` absent).

- [ ] **Step 3 : Créer `policy.example.yml`**

```yaml
# policy.example.yml — exemple de politique du coordinateur.
# Ordre = priorité : la première règle qui matche gagne ; défaut = deny (fail-closed).
rules:
  - match: { capability: "crowdsec.get_*" }
    effect: allow
    reason: "lectures crowdsec sans risque (décisions, alertes, métriques)"

  - match:
      capability: "crowdsec.ban_ip"
      args: { ip: { op: present } }
    effect: approve
    reason: "bannissement d'IP : validation humaine requise"

  - match: { capability: "crowdsec.*" }
    effect: deny
    reason: "toute autre action crowdsec refusée par défaut"
```

- [ ] **Step 4 : Éditer `pyproject.toml`**

Ajouter `uvicorn` aux deps core et déclarer le script :

```toml
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

[project.scripts]
cyber-coordinator = "coordinator.app:run"
```

- [ ] **Step 5 : Ajouter la section README « Lancer le coordinateur »**

Dans `README.md`, après la section « Déploiement & backends », ajouter :

````markdown
### Lancer le coordinateur

```bash
export COORDINATOR_API_KEY=...            # clé d'auth (obligatoire)
export COORDINATOR_SESSION_KEY=...        # clé Fernet base64 (obligatoire)
export COORDINATOR_POLICY_FILE=policy.yml # règles (obligatoire ; cf. policy.example.yml)
export AGENT_SERVER_URL=http://localhost:3000   # serveur d'agents
cyber-coordinator                          # lance uvicorn sur COORDINATOR_HOST:PORT (défaut 127.0.0.1:8080)
```

Le coordinateur refuse de démarrer si une variable obligatoire manque ou si
`policy.yml` est invalide (fail-closed). Copier `policy.example.yml` comme point
de départ. `GET /coordinator/health` sert la readiness (sans auth).
````

- [ ] **Step 6 : Lancer les tests + suite complète**

Run: `.venv/bin/pytest tests/test_entrypoint.py -q && .venv/bin/pip install -e . >/dev/null 2>&1 && .venv/bin/pytest -q`
Expected: PASS ; réinstall editable OK ; suite complète verte.

- [ ] **Step 7 : Commit**

```bash
git add pyproject.toml policy.example.yml README.md tests/test_entrypoint.py
git commit -m "feat: console script cyber-coordinator, policy.example.yml, doc de lancement"
```

---

## Auto-revue du plan (checklist auteur)

**Couverture du spec :**
- `FileAuditSink` (audit durable JSONL) → Task 1. ✅
- Extracteur regex → Task 2. ✅
- `config.py` fail-closed + policy.yml → Task 3 (+ format/exemple Task 8). ✅
- `create_default_app` (assemblage en lifespan) + refactor `build_app` → Task 7. ✅
- Câblage env→agent (serveur d'agents) → Task 6. ✅
- Console script `cyber-coordinator` + uvicorn + policy.example.yml + README → Task 8. ✅
- Dette `rule_reason` → Task 4. ✅
- Dette no-silent-simulation → Task 5. ✅
- Non-régression 114 tests + garde-fou d'import léger → vérifié Tasks 4,7 (test_app B, test_portability). ✅

**Raffinements du terrain (vs spec) :** un seul client vers le serveur d'agents (le serveur héberge tous les agents ; multi-serveur par agent → D3) ; `build_app` refactoré pour lire `app.state.loop` (permet l'assemblage async en lifespan sans casser les tests B) ; `entry_from_verdict` gagne un param `rule_reason` (plus propre que reconstruire une Rule).

**Cohérence des types** : `CoordinatorConfig`/`load_config` (T3) consommés T7 ; `FileAuditSink` (T1) consommé T7 ; `build_regex_extractor` (T2) consommé T7 ; `discover_agents`/`assemble_loop`/`AssemblyError` (T7) ; `resolve_lora_models`/`build_infer_client` (T6) ; `entry_from_verdict(..., rule_reason=)` (T4) cohérent avec l'appel dans loop.

**Placeholders** : aucun — chaque étape porte le code réel ou le remplacement exact. Les ellipses de `_register_routes`/lifespan sont du code complet montré.

**Dette reportée (→ D2/D3)** : LICENSE, metadata pyproject de distribution, sdist/wheel, Docker/compose → D2 ; multi-tenant, rétention/ISM, rotation d'audit, multi-serveur d'agents → D3.
