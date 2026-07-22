# Portabilité modèles & runtime — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre `cyber-agent-engine` déployable par un tiers avec `pip install` + une clé API, sans GPU/`torch`/`unsloth`/`vllm` ni le paquet fantôme `factory`, en conservant les agents LoRA comme option enfichable.

**Architecture:** Corriger les imports `factory.clients`→`clients` / `factory.agents`→`agents` (le code réel est déjà dans `clients/` et `agents/`), isoler la seule dépendance GPU (`clients/native_vllm_client.py` + `unsloth`) derrière un import paresseux et un extra pip `[gpu]`, et ajouter un backend d'inférence agent OpenAI-compatible (HTTP) pour servir les LoRA sans in-process. Un test-garde-fou vérifie qu'aucune dépendance lourde n'est importée au chargement.

**Tech Stack:** Python 3.11, httpx, pytest, tomllib. Extra `[gpu]` : torch, vllm, unsloth.

## Global Constraints

- **CQI > 9 dès le départ, test-first.**
- **Fail-closed lisible** : une fonctionnalité GPU demandée sans l'extra `[gpu]` → message d'erreur clair (« requiert l'extra `[gpu]` »), JAMAIS un `ImportError` brut de torch. Aucun backend d'inférence agent configuré → erreur explicite, pas de simulation silencieuse.
- **Aucune dépendance lourde à l'import** : `import agents`, `import clients`, `import coordinator.app` ne doivent charger ni `torch`, ni `vllm`, ni `unsloth`.
- **Nom `clients/` conservé** (le préfixe `factory` était l'artefact d'un ancien monorepo ; on ne rend PAS le dépôt installable sous `factory`).
- **Non-régression** : les 99 tests des sous-projets A+B restent verts.
- **DRY / YAGNI** : réutiliser le parsing (`_parse_model_output`) et le prompt builder (`_build_chat_messages`) existants ; ne pas réimplémenter un client OpenAI complet.
- **Commits** : `type(scope): sujet` minuscules, sans emoji, **sans** `Co-Authored-By`, **sans** mention d'IA. Docstrings en français.
- ruff clean sur chaque module ET son test ; mypy : ne pas régresser (`.venv/bin/mypy` sur le périmètre configuré). Les modules legacy touchés (base.py, server.py, agents/*) portent une dette ruff/mypy pré-existante hors périmètre — vérifier l'absence de NOUVELLE anomalie sur les lignes modifiées, pas nettoyer tout le fichier.

---

### Task 1 : Neutraliser `TOOL_CALL_SCHEMA` (le sortir de la dépendance torch)

**Files:**
- Create: `clients/tool_call_schema.py`
- Modify: `clients/native_vllm_client.py` (déplacer la définition, ré-exporter)
- Modify: `agents/base.py:19-22` (importer depuis le module neutre)
- Test: `tests/clients/test_tool_call_schema.py`
- Create: `tests/clients/__init__.py`

**Interfaces:**
- Produces: `clients/tool_call_schema.py::TOOL_CALL_SCHEMA: dict` — le JSON-schema des tool_calls, importable sans aucune dépendance lourde.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/clients/test_tool_call_schema.py
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_schema_is_a_dict():
    from clients.tool_call_schema import TOOL_CALL_SCHEMA
    assert isinstance(TOOL_CALL_SCHEMA, dict)
    assert TOOL_CALL_SCHEMA  # non vide


def test_importing_schema_does_not_pull_torch():
    code = (
        "import sys; import clients.tool_call_schema; "
        "assert 'torch' not in sys.modules and 'vllm' not in sys.modules"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(_ROOT),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `.venv/bin/pytest tests/clients/test_tool_call_schema.py -q`
Expected: FAIL (`No module named 'clients.tool_call_schema'`).

- [ ] **Step 3 : Créer `clients/tool_call_schema.py`**

Ouvrir `clients/native_vllm_client.py`, repérer le bloc `TOOL_CALL_SCHEMA: dict = { ... }` (commence ligne 20). Le **couper** et le coller intégralement dans un nouveau fichier :

```python
# clients/tool_call_schema.py
"""Schéma JSON des tool_calls — module neutre, sans dépendance lourde.

Extrait de native_vllm_client.py pour qu'importer le schéma (ex. dans base.py)
ne charge jamais torch/vllm.
"""

from __future__ import annotations

TOOL_CALL_SCHEMA: dict = {
    # ... coller ici le dict exact déplacé depuis native_vllm_client.py ...
}
```

Dans `clients/native_vllm_client.py`, remplacer la définition supprimée par un ré-export (pour tout code qui l'importait depuis là) :

```python
from clients.tool_call_schema import TOOL_CALL_SCHEMA  # ré-export rétro-compatible
```

- [ ] **Step 4 : Mettre à jour `agents/base.py`**

Remplacer le bloc `agents/base.py:19-22` :

```python
try:
    from factory.clients.native_vllm_client import TOOL_CALL_SCHEMA
except ImportError:
    TOOL_CALL_SCHEMA = None
```

par (le module neutre est toujours importable, plus besoin du fallback) :

```python
from clients.tool_call_schema import TOOL_CALL_SCHEMA
```

- [ ] **Step 5 : Lancer les tests, vérifier le succès**

Run: `.venv/bin/pytest tests/clients/test_tool_call_schema.py -q && .venv/bin/ruff check clients/tool_call_schema.py tests/clients/test_tool_call_schema.py`
Expected: PASS ; ruff clean.

- [ ] **Step 6 : Commit**

```bash
git add clients/tool_call_schema.py clients/native_vllm_client.py agents/base.py tests/clients/
git commit -m "refactor(clients): extraire TOOL_CALL_SCHEMA dans un module neutre sans torch"
```

---

### Task 2 : Renommer les imports `factory.*` et rendre l'import vLLM du serveur paresseux

**Files:**
- Modify: `agents/crowdsec_agent.py:73`, `agents/wireguard_agent.py:66`, `agents/pfsense_agent.py:59`, `agents/opnsense/_base.py:150,164,175`, `agents/base.py:106`, `agents/tool_agents.py:7-10,35`, `agents/__init__.py:13`, `coordinator/llm/coordinator_llm.py:112`, `server.py:31`
- Create: `clients/gpu.py`
- Test: `tests/clients/test_gpu.py`

**Interfaces:**
- Produces: `clients/gpu.py::load_native_vllm_client() -> type` — importe et renvoie la classe `NativeVLLMClient`, en levant un `GpuExtraRequired` (message clair) si torch/vllm absent. `clients/gpu.py::GpuExtraRequired(RuntimeError)`.

- [ ] **Step 1 : Écrire le test qui échoue (helper GPU)**

```python
# tests/clients/test_gpu.py
import builtins
import pytest
from clients.gpu import load_native_vllm_client, GpuExtraRequired


def test_missing_extra_raises_clear_error(monkeypatch):
    real_import = builtins.__import__

    def _fake_import(name, *a, **k):
        if name.startswith("clients.native_vllm_client") or name == "torch" or name.startswith("vllm"):
            raise ImportError("No module named 'torch'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(GpuExtraRequired) as exc:
        load_native_vllm_client()
    assert "[gpu]" in str(exc.value)
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `.venv/bin/pytest tests/clients/test_gpu.py -q`
Expected: FAIL (`No module named 'clients.gpu'`).

- [ ] **Step 3 : Créer `clients/gpu.py`**

```python
"""Chargement paresseux des composants GPU, avec message d'erreur lisible.

Le loader vLLM in-process (`NativeVLLMClient`) tire torch+vllm. On ne l'importe
JAMAIS au chargement d'un module : uniquement à la demande, via ce helper, qui
transforme un `ImportError` brut en une erreur explicite indiquant l'extra `[gpu]`.
"""

from __future__ import annotations

from typing import Any


class GpuExtraRequired(RuntimeError):
    """Une fonctionnalité GPU (loader vLLM in-process) a été demandée sans l'extra [gpu]."""


def load_native_vllm_client() -> Any:
    try:
        from clients.native_vllm_client import NativeVLLMClient
    except ImportError as exc:
        raise GpuExtraRequired(
            "Le loader vLLM in-process requiert l'extra GPU : "
            "pip install cyber-agent-engine[gpu]"
        ) from exc
    return NativeVLLMClient
```

- [ ] **Step 4 : Renommer tous les imports `factory.*`**

Appliquer ces remplacements exacts (le code cible existe déjà sous `clients/` et `agents/`) :

- `agents/crowdsec_agent.py:73` : `from factory.clients.crowdsec_client import CrowdSecClient, CrowdSecAPIError` → `from clients.crowdsec_client import CrowdSecClient, CrowdSecAPIError`
- `agents/wireguard_agent.py:66` : `from factory.clients import WireGuardAPIClient, WireGuardLinuxClient` → `from clients import WireGuardAPIClient, WireGuardLinuxClient`
- `agents/pfsense_agent.py:59` : `from factory.clients.pfsense_api_client import PfSenseAPIClient` → `from clients.pfsense_api_client import PfSenseAPIClient`
- `agents/opnsense/_base.py:150` : `from factory.clients import OPNsenseAPIClient` → `from clients import OPNsenseAPIClient`
- `agents/opnsense/_base.py:164` : `from factory.clients.pfsense_client import PfSenseClient` → `from clients.pfsense_client import PfSenseClient`
- `agents/opnsense/_base.py:175` : `from factory.clients.linux_sys_client import LinuxSysClient` → `from clients.linux_sys_client import LinuxSysClient`
- `agents/base.py:106` : `from factory.clients.ollama_client import OllamaClient` → `from clients.ollama_client import OllamaClient`
- `agents/tool_agents.py:7-10` : `from factory.agents import …` → `from agents import …` (les 4 lignes)
- `agents/tool_agents.py:35` et `agents/__init__.py:13` : corriger les mentions `factory.agents` en `agents` dans les docstrings/messages.
- `coordinator/llm/coordinator_llm.py:112` : `from factory.clients.native_vllm_client import NativeVLLMClient` → utiliser le helper : remplacer cette ligne par `from clients.gpu import load_native_vllm_client` (en tête de la fonction `_init_vllm`) puis `NativeVLLMClient = load_native_vllm_client()`.

- [ ] **Step 5 : Rendre `server.py:31` paresseux**

`server.py:31` fait un import **au niveau module** : `from factory.clients.native_vllm_client import NativeVLLMClient` — il tire torch au chargement du serveur d'agent. Le supprimer de l'entête et l'obtenir à la demande dans la (les) fonction(s) qui construi(sen)t le client vLLM (dans `lifespan`/`_discover_lora_adapters`), via le helper :

```python
from clients.gpu import load_native_vllm_client
NativeVLLMClient = load_native_vllm_client()  # lève GpuExtraRequired si [gpu] absent
```

Repérer les usages de `NativeVLLMClient` dans `server.py` (construction du client dans le lifespan) et déplacer l'obtention de la classe juste avant, dans le corps de la fonction. Ne pas changer la logique de construction, seulement le lieu de l'import.

- [ ] **Step 6 : Vérifier — plus aucun `factory.` et imports légers OK**

Run:
```bash
grep -rn 'factory\.' --include='*.py' . | grep -v '/\.venv/' | grep -v '/tests/' | grep -v conftest.py
.venv/bin/pytest tests/clients/test_gpu.py -q
```
Expected: le grep ne renvoie **plus aucune ligne de code** (seuls restent d'éventuels commentaires/tests traités en Task 3) ; test gpu PASS.

- [ ] **Step 7 : Commit**

```bash
git add agents/ coordinator/llm/coordinator_llm.py server.py clients/gpu.py tests/clients/test_gpu.py
git commit -m "refactor: renommer les imports factory vers clients/agents et paresser le loader vLLM"
```

---

### Task 3 : Supprimer le mock `factory` et poser le garde-fou d'import léger

**Files:**
- Delete: `conftest.py` (le mock factory) — ou vider son contenu factory
- Modify: `tests/agents/test_agent_server_structured.py` (retirer le shim `factory.clients.native_vllm_client`)
- Test: `tests/test_portability.py`
- Create: `tests/portability` non — placer à `tests/test_portability.py`

**Interfaces:**
- Consumes: le renommage de Task 2 (plus aucun import `factory.*`).

- [ ] **Step 1 : Écrire le garde-fou de portabilité (qui doit déjà passer après Tasks 1-2)**

```python
# tests/test_portability.py
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _import_in_subprocess(module_csv: str) -> subprocess.CompletedProcess:
    code = (
        "import sys\n"
        f"import {module_csv}\n"
        "heavy = {'torch', 'vllm', 'unsloth'} & set(sys.modules)\n"
        "assert not heavy, f'deps lourdes importees au chargement: {heavy}'\n"
    )
    return subprocess.run([sys.executable, "-c", code], cwd=str(_ROOT),
                          capture_output=True, text=True)


def test_import_agents_is_light():
    r = _import_in_subprocess("agents")
    assert r.returncode == 0, r.stderr


def test_import_clients_is_light():
    r = _import_in_subprocess("clients")
    assert r.returncode == 0, r.stderr


def test_import_coordinator_app_is_light():
    r = _import_in_subprocess("coordinator.app")
    assert r.returncode == 0, r.stderr
```

- [ ] **Step 2 : Lancer, constater qu'il passe déjà (imports corrigés) mais que le mock est encore là**

Run: `.venv/bin/pytest tests/test_portability.py -q`
Expected: PASS (le subprocess n'utilise pas `conftest.py`, donc il teste l'import réel). Si un `import agents` échoue dans le subprocess, c'est qu'un `factory.*` a été manqué en Task 2 — le corriger.

- [ ] **Step 3 : Supprimer le mock `factory` de `conftest.py`**

Le fichier `conftest.py` racine ne contient que le mock factory (`sys.modules['factory'] = MagicMock()` / `sys.modules['factory.clients'] = MagicMock()`). Comme il n'y a plus d'import `factory.*`, il est inutile :

```bash
git rm conftest.py
```

(Si `conftest.py` contenait d'autres réglages pytest — vérifier d'abord `cat conftest.py` — ne retirer que les lignes factory et conserver le reste.)

- [ ] **Step 4 : Retirer le shim local dans `test_agent_server_structured.py`**

Dans `tests/agents/test_agent_server_structured.py`, retirer la ligne
`sys.modules.setdefault("factory.clients.native_vllm_client", MagicMock())` (≈ ligne 31) et les commentaires du docstring qui l'expliquent (lignes ~4-14). `base.py` n'importe plus rien de lourd (Task 1), donc importer `server` ne nécessite plus ce shim. Garder le reste du test intact.

- [ ] **Step 5 : Lancer la suite entière**

Run: `.venv/bin/pytest -q`
Expected: tout vert (99 tests A+B + les nouveaux), y compris `test_agent_server_structured.py` **sans** le shim. Si un import échoue faute de mock, c'est un `factory.*` résiduel (Task 2) ou une vraie dépendance manquante — investiguer, ne pas réintroduire le mock.

- [ ] **Step 6 : Commit**

```bash
git add -A
git commit -m "test: garde-fou d import leger + suppression du mock factory devenu inutile"
```

---

### Task 4 : `pyproject.toml` — deps core minces, extra `[gpu]`, packaging

**Files:**
- Modify: `pyproject.toml`
- Test: `tests/test_packaging.py`

**Interfaces:**
- Produces: extra `[gpu]` (`torch`, `vllm`, `unsloth`) ; `packages.find.include` couvrant `clients*`, `agents*`, `coordinator*`.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_packaging.py
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _cfg() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


def test_core_deps_have_no_heavy_ml():
    deps = _cfg()["project"]["dependencies"]
    joined = " ".join(deps).lower()
    for heavy in ("torch", "vllm", "unsloth"):
        assert heavy not in joined, f"{heavy} ne doit pas être une dep core"
    for needed in ("fastapi", "requests", "anthropic"):
        assert any(needed in d.lower() for d in deps), f"{needed} manquant des deps core"


def test_gpu_extra_declared():
    extras = _cfg()["project"].get("optional-dependencies", {})
    assert "gpu" in extras
    joined = " ".join(extras["gpu"]).lower()
    assert "torch" in joined and "vllm" in joined and "unsloth" in joined


def test_packages_include_covers_runtime():
    include = _cfg()["tool"]["setuptools"]["packages"]["find"]["include"]
    for pkg in ("clients*", "agents*", "coordinator*", "core*"):
        assert pkg in include
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_packaging.py -q`
Expected: FAIL (extra `gpu` absent, includes incomplets, deps core sans fastapi/requests/anthropic).

- [ ] **Step 3 : Éditer `pyproject.toml`**

Compléter `[project].dependencies` (ajouter les deps core réellement importées, sans ML) :

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
]

[project.optional-dependencies]
gpu = [
    "torch>=2.1.0",
    "vllm>=0.6.0",
    "unsloth",
]
```

Étendre l'include du packaging :

```toml
[tool.setuptools.packages.find]
where = ["."]
include = ["core*", "clients*", "agents*", "coordinator*"]
```

- [ ] **Step 4 : Lancer les tests + réinstaller l'editable**

Run:
```bash
.venv/bin/pytest tests/test_packaging.py -q
.venv/bin/pip install -e . >/dev/null 2>&1 && .venv/bin/python -c "import agents, clients, coordinator.app; print('ok')"
```
Expected: tests PASS ; import « ok » ; aucun torch tiré (déjà couvert par `tests/test_portability.py`).

- [ ] **Step 5 : Commit**

```bash
git add pyproject.toml tests/test_packaging.py
git commit -m "build: deps core minces, extra [gpu], packaging clients/agents/coordinator"
```

---

### Task 5 : Backend d'inférence agent OpenAI-compatible (enfichable)

**Files:**
- Create: `clients/openai_compat_client.py`
- Modify: `agents/base.py` (`__init__` : params `openai_client`, `lora_model` ; `_infer_function` : nouvel ordre + fail-closed ; nouvelle méthode `_infer_with_openai_compat`)
- Test: `tests/clients/test_openai_compat_client.py`, `tests/agents/test_infer_backend_selection.py`

**Interfaces:**
- Produces:
  - `clients/openai_compat_client.py::OpenAICompatClient(base_url: str, api_key: str = "")` avec `async def chat(self, messages: list[dict], model: str, max_tokens: int = 256) -> str` — POST `{base_url}/chat/completions`, renvoie `choices[0].message.content`.
  - `agents/base.py::ToolAgent.__init__` accepte `openai_client=None` et `lora_model: str = ""`.
  - `ToolAgent._infer_with_openai_compat(user_request) -> FunctionCall`.
  - `ToolAgent._infer_function` : ordre `openai_client → ollama_client → vllm_client → model(unsloth) → NoInferenceBackend`.
  - `agents/base.py::NoInferenceBackend(RuntimeError)`.
- Consumes: `_build_chat_messages`, `_parse_model_output` (existants, inchangés).

- [ ] **Step 1 : Écrire le test du transport (faux httpx)**

```python
# tests/clients/test_openai_compat_client.py
import httpx
import pytest
from clients.openai_compat_client import OpenAICompatClient


@pytest.mark.asyncio
async def test_chat_posts_and_extracts_content():
    captured = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "HELLO"}}]})

    transport = httpx.MockTransport(_handler)
    client = OpenAICompatClient(base_url="http://x/v1", api_key="k")
    client._client = httpx.AsyncClient(transport=transport, base_url="http://x/v1")
    out = await client.chat([{"role": "user", "content": "hi"}], model="crowdsec-lora")
    assert out == "HELLO"
    assert captured["json"]["model"] == "crowdsec-lora"
    assert captured["url"].endswith("/chat/completions")
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/clients/test_openai_compat_client.py -q`
Expected: FAIL (`No module named 'clients.openai_compat_client'`).

- [ ] **Step 3 : Implémenter `clients/openai_compat_client.py`**

```python
"""Client d'inférence OpenAI-compatible (HTTP) — sert un LoRA sans dépendance GPU.

Sert de transport pour le chemin NL d'un agent : POST /chat/completions vers un
endpoint OpenAI-compatible (vLLM multi-LoRA, llama.cpp, Ollama /v1…), le `model`
étant le nom du LoRA de l'outil. Aucune dépendance lourde (juste httpx).
"""

from __future__ import annotations

from typing import Any

import httpx


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url, headers=headers, timeout=httpx.Timeout(timeout)
        )

    async def chat(self, messages: list[dict[str, Any]], model: str, max_tokens: int = 256) -> str:
        resp = await self._client.post(
            "/chat/completions",
            json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.1},
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data["choices"][0]["message"]["content"])

    async def aclose(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 4 : Écrire le test de sélection de backend + fail-closed**

```python
# tests/agents/test_infer_backend_selection.py
import pytest
from agents.base import ToolAgent, NoInferenceBackend, FunctionCall


class _Agent(ToolAgent):
    def __init__(self, **kw):
        super().__init__(tool_name="t", model_path=None, **kw)

    def _register_functions(self):
        return {"get_metrics": self._get_metrics}

    async def _get_metrics(self):
        return {"ok": True}


class _FakeOpenAI:
    def __init__(self):
        self.calls = []

    async def chat(self, messages, model, max_tokens=256):
        self.calls.append((model, messages))
        return '[{"name": "get_metrics", "arguments": "{}"}]'


@pytest.mark.asyncio
async def test_openai_backend_selected_and_used():
    fake = _FakeOpenAI()
    agent = _Agent(openai_client=fake, lora_model="crowdsec-lora")
    fc = await agent._infer_function("montre les métriques")
    assert isinstance(fc, FunctionCall)
    assert fake.calls and fake.calls[0][0] == "crowdsec-lora"
    assert fc.function == "get_metrics"


@pytest.mark.asyncio
async def test_no_backend_fails_closed():
    agent = _Agent()  # aucun backend d'inférence
    with pytest.raises(NoInferenceBackend):
        await agent._infer_function("montre les métriques")
```

- [ ] **Step 5 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/agents/test_infer_backend_selection.py -q`
Expected: FAIL (`_Agent` ne connaît pas `openai_client`/`lora_model` ; `NoInferenceBackend` absent).

- [ ] **Step 6 : Modifier `agents/base.py`**

1. Ajouter en haut du module la classe d'erreur :

```python
class NoInferenceBackend(RuntimeError):
    """Aucun backend d'inférence NL configuré pour cet agent (execute_direct reste dispo)."""
```

2. Dans `ToolAgent.__init__`, ajouter les paramètres et les stocker (à côté de `vllm_client`) :

```python
    def __init__(
        self,
        tool_name: str,
        model_path: str,
        api_config: Optional[Dict] = None,
        ollama_config: Optional[Dict] = None,
        vllm_client: Any = None,
        openai_client: Any = None,
        lora_model: str = "",
    ):
        ...
        self.vllm_client = vllm_client
        self.openai_client = openai_client
        self.lora_model = lora_model
        ...
```

3. Ajouter la méthode d'inférence OpenAI-compatible (réutilise le prompt builder et le parseur existants) :

```python
    async def _infer_with_openai_compat(self, user_request: str) -> "FunctionCall":
        """Inférence NL via un endpoint OpenAI-compatible servant le LoRA de l'outil."""
        messages = self._build_chat_messages(user_request)
        content = await self.openai_client.chat(messages, model=self.lora_model)
        return self._parse_model_output(content, user_request)
```

4. Réécrire l'ordre de `_infer_function` (le nouveau backend en tête ; la simulation silencieuse remplacée par une erreur fail-closed) :

```python
    async def _infer_function(self, user_request: str) -> FunctionCall:
        if self.openai_client:
            return await self._infer_with_openai_compat(user_request)
        if self.ollama_client:
            return await self._infer_with_ollama(user_request)
        if self.vllm_client:
            return await self._infer_with_vllm(user_request)
        if self.model is not None and self.tokenizer is not None:
            return await self._infer_with_lora(user_request)
        raise NoInferenceBackend(
            "Aucun backend d'inférence configuré (AGENT_INFER_BASE_URL/ollama/[gpu]). "
            "Le chemin structuré execute_direct reste disponible sans modèle."
        )
```

(Ne pas supprimer `_infer_with_simulation` : elle reste utilisée par les fallback internes de `_infer_with_lora`/ollama.)

- [ ] **Step 7 : Lancer les tests**

Run: `.venv/bin/pytest tests/clients/test_openai_compat_client.py tests/agents/test_infer_backend_selection.py -q && .venv/bin/ruff check clients/openai_compat_client.py tests/clients/test_openai_compat_client.py tests/agents/test_infer_backend_selection.py`
Expected: PASS ; ruff clean sur les nouveaux fichiers.

- [ ] **Step 8 : Non-régression + commit**

Run: `.venv/bin/pytest -q` (doit rester vert).
```bash
git add clients/openai_compat_client.py agents/base.py tests/clients/test_openai_compat_client.py tests/agents/test_infer_backend_selection.py
git commit -m "feat(agents): backend d inference OpenAI-compatible enfichable + selection fail-closed"
```

---

### Task 6 : Coordinateur — gate `[gpu]` du backend vLLM + conformité au proposeur

**Files:**
- Modify: `coordinator/llm/coordinator_llm.py` (`_init_vllm` via helper `[gpu]`)
- Modify: `coordinator/proposer.py` (rendre `ChatLLM` `@runtime_checkable`)
- Test: `tests/coordinator/test_llm_conformance.py`

**Interfaces:**
- Consumes: `clients.gpu.load_native_vllm_client` (Task 2), `coordinator.proposer.ChatLLM` (sous-projet B).
- Produces: `ChatLLM` décoré `@runtime_checkable` ; `CoordinatorLLM` conforme au Protocol `ChatLLM`.

- [ ] **Step 1 : Écrire le test de conformité**

```python
# tests/coordinator/test_llm_conformance.py
import inspect
from coordinator.proposer import ChatLLM
from coordinator.llm.coordinator_llm import CoordinatorLLM


def test_coordinator_llm_is_chatllm():
    # __init__ ne fait aucune I/O réseau (backend initialisé seulement dans init()).
    assert isinstance(CoordinatorLLM(), ChatLLM)


def test_chat_signature_matches_protocol():
    sig = inspect.signature(CoordinatorLLM.chat)
    params = list(sig.parameters)
    assert params[0] == "self" and "messages" in params and "max_tokens" in params
    assert inspect.iscoroutinefunction(CoordinatorLLM.chat)
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/coordinator/test_llm_conformance.py -q`
Expected: FAIL (`isinstance` sur un `Protocol` non `runtime_checkable` lève `TypeError`).

- [ ] **Step 3 : Rendre `ChatLLM` runtime-checkable**

Dans `coordinator/proposer.py`, importer `runtime_checkable` et décorer le Protocol :

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class ChatLLM(Protocol):
    async def chat(self, messages: list[dict[str, str]], max_tokens: int = 1024) -> str: ...
```

- [ ] **Step 4 : Gater le backend vLLM du coordinateur via le helper `[gpu]`**

Dans `coordinator/llm/coordinator_llm.py::_init_vllm`, remplacer l'obtention de `NativeVLLMClient` (déjà renommée en Task 2) par le helper qui lève un message clair si l'extra manque :

```python
        from clients.gpu import load_native_vllm_client
        NativeVLLMClient = load_native_vllm_client()  # lève GpuExtraRequired si [gpu] absent
```

(Le reste de `_init_vllm` inchangé. Aucun autre chemin du coordinateur ne doit importer torch au chargement.)

- [ ] **Step 5 : Lancer les tests**

Run: `.venv/bin/pytest tests/coordinator/test_llm_conformance.py -q && .venv/bin/pytest tests/coordinator/test_proposer.py -q`
Expected: PASS (conformité OK ; les tests B du proposeur restent verts après l'ajout de `@runtime_checkable`).

- [ ] **Step 6 : Commit**

```bash
git add coordinator/llm/coordinator_llm.py coordinator/proposer.py tests/coordinator/test_llm_conformance.py
git commit -m "feat(coordinator): gate [gpu] du backend vllm + ChatLLM runtime_checkable"
```

---

### Task 7 : Documentation de déploiement

**Files:**
- Modify: `README.md` (section « Déploiement & backends »)

**Interfaces:** aucune (documentation).

- [ ] **Step 1 : Ajouter la section au README**

Insérer une section décrivant précisément :

````markdown
## Déploiement & backends

### Installation

```bash
pip install cyber-agent-engine          # cœur : coordinateur (API) + agents structurés, sans GPU
pip install cyber-agent-engine[gpu]     # + loader vLLM/LoRA in-process (torch, vllm, unsloth)
```

### Backend du coordinateur (LLM de raisonnement)

| Variable                | Rôle                                                        |
|-------------------------|-------------------------------------------------------------|
| `COORDINATOR_BACKEND`   | `anthropic` (défaut) \| `openai` \| `vllm` (\[gpu\]) \| `ollama` |
| `ANTHROPIC_API_KEY`     | clé API (backend anthropic)                                 |
| `OPENAI_BASE_URL`       | endpoint OpenAI-compatible (OpenRouter, vLLM-HTTP, llama.cpp-server, Ollama `/v1`) |
| `OPENAI_API_KEY`        | clé/token du endpoint openai-compatible                     |

Un endpoint **OpenAI-compatible** couvre OpenRouter, un serveur vLLM, llama.cpp
en mode serveur, LocalAI, et l'endpoint `/v1` d'Ollama — aucun GPU requis côté
`cyber-agent-engine`.

### Agents LoRA (chemin NL optionnel)

Le chemin de confiance (exécution structurée) ne requiert aucun modèle. Pour
activer l'interprétation en langage naturel par LoRA :

1. Télécharger les LoRA publics depuis HuggingFace (opnsense/wireguard/crowdsec).
2. Les servir derrière un endpoint OpenAI-compatible (vLLM multi-LoRA, llama.cpp…),
   le nom de modèle = nom du LoRA.
3. Configurer l'agent :

| Variable                | Rôle                                                |
|-------------------------|-----------------------------------------------------|
| `AGENT_INFER_BASE_URL`  | endpoint OpenAI-compatible servant les LoRA         |
| `AGENT_INFER_API_KEY`   | clé/token de cet endpoint                           |
| `AGENT_LORA_MODELS`     | mapping outil→nom de LoRA (ou `CROWDSEC_LORA_MODEL=…`) |

Sans backend d'inférence configuré, le chemin NL renvoie une erreur explicite ;
le chemin structuré (`execute_direct`) reste toujours disponible.
````

- [ ] **Step 2 : Vérifier + commit**

Run: `.venv/bin/pytest -q` (aucun impact code, doit rester vert).
```bash
git add README.md
git commit -m "docs: section deploiement & backends (extras pip, coordinateur, agents LoRA)"
```

---

## Auto-revue du plan (checklist auteur)

**Couverture du spec :**
- Chantier 1 (renommage imports) → Tasks 1 (schema), 2 (sweep + server lazy). ✅
- Chantier 2 (TOOL_CALL_SCHEMA neutre + suppression mock) → Task 1 + Task 3. ✅
- Chantier 3 (isolation GPU, extras pip, fail-safe) → Task 2 (helper gpu), Task 4 (pyproject), Task 6 (coordinateur gate). ✅
- Chantier 4 (backend agent OpenAI-compatible + sélection fail-closed) → Task 5. ✅
- Chantier 5 (coordinateur hygiène + conformité proposeur) → Task 6. ✅
- Tests (invariant portabilité, renommage, schema, backend, fail-safe, conformité, non-régression) → Tasks 1,3,4,5,6. ✅
- Documentation de déploiement → Task 7. ✅

**Cohérence des types** : `NoInferenceBackend`/`openai_client`/`lora_model` définis Task 5 ; `GpuExtraRequired`/`load_native_vllm_client` définis Task 2 et consommés Tasks 5(non)/6 ; `ChatLLM` runtime_checkable Task 6 cohérent avec la signature `chat(messages, max_tokens)`.

**Placeholders** : aucun — chaque étape porte le code réel ou le remplacement exact ligne par ligne. La seule ellipse (`...` dans `TOOL_CALL_SCHEMA` et `__init__`) est un déplacement de code existant, pas un contenu à inventer (Task 1 dit « coller le dict exact », Task 5 montre l'`__init__` complet à compléter).

**Dette reportée (→ D)** : assemblage runtime `create_default_app`, licence, packaging de distribution, ISM, multi-tenant. LoRA training (dépôts privés) hors périmètre.
