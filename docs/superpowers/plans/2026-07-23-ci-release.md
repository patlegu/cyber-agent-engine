# CI de release & en-têtes SPDX (D3b) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Outiller la release automatisée de `cyber-agent-engine` (CI de test + publication PyPI OIDC / GHCR sur tag) et l'hygiène de licence par fichier (en-têtes SPDX), sans toucher le code applicatif.

**Architecture:** En-têtes SPDX sur le code source first-party (+ test d'enforcement par motif). Deux workflows GitHub Actions : `ci.yml` (pytest+mypy+ruff sur la surface maintenue, push/PR) et `release.yml` (tag `v*` → test → PyPI Trusted Publishing OIDC → GHCR via GITHUB_TOKEN). Les workflows ne s'exécutent pas en test local → validés statiquement (parse YAML).

**Tech Stack:** GitHub Actions, PyYAML, `python -m build`, `pypa/gh-action-pypi-publish` (OIDC), `docker/build-push-action`.

## Global Constraints

- **CQI > 9, test-first.** Tests déterministes (parse YAML + enforcement SPDX) ; **aucun** workflow exécuté en test.
- **Gate ruff sur la surface source maintenue** (la liste `[tool.mypy].files` — vérifiée `ruff`-clean), **pas** `ruff check .` (689 findings legacy) ni `tests/` (27 findings legacy dans `tests/core/*`, hors périmètre). `mypy` = périmètre `[tool.mypy].files`. `pytest` = tous les tests.
- **Les workflows sont commités mais inertes** jusqu'à un tag `v*` / la config du trusted publisher.
- **En-têtes SPDX** : `# SPDX-License-Identifier: AGPL-3.0-or-later` en tête (ligne 1, aucun shebang first-party) des `.py` sous `core/`, `coordinator/`, `agents/`, `clients/` + `server.py`. **Exclus** : `tests/`, `dashboard/`.
- **Non-régression** : les 187 tests A→D3a restent verts ; les en-têtes SPDX (commentaires) n'ajoutent aucune anomalie ruff/mypy.
- **Piège YAML** : GitHub Actions utilise la clé `on:` que `yaml.safe_load` interprète comme le **booléen `True`** (YAML 1.1). Les tests de validation lisent la clé via `wf.get(True, wf.get("on"))`.
- **Commits** : `type(scope): sujet` minuscules, sans emoji, **sans** `Co-Authored-By`, **sans** mention d'IA.

---

### Task 1 : En-têtes SPDX + enforcement

**Files:**
- Modify: les ~85 `.py` first-party (`core/`, `coordinator/`, `agents/`, `clients/`, `server.py`) — ajout d'une ligne d'en-tête
- Test: `tests/test_spdx_headers.py`

**Interfaces:** aucune (en-têtes + test).

- [ ] **Step 1 : Écrire le test d'enforcement qui échoue**

```python
# tests/test_spdx_headers.py
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SPDX = "SPDX-License-Identifier: AGPL-3.0-or-later"
_DIRS = ("core", "coordinator", "agents", "clients")
_ROOT_FILES = ("server.py",)


def _first_party_sources() -> list[Path]:
    files: list[Path] = []
    for d in _DIRS:
        files.extend((_ROOT / d).rglob("*.py"))
    files.extend(_ROOT / f for f in _ROOT_FILES)
    return files


def test_every_first_party_source_has_spdx_header():
    missing = []
    for f in _first_party_sources():
        head = "\n".join(f.read_text(encoding="utf-8").splitlines()[:3])
        if _SPDX not in head:
            missing.append(str(f.relative_to(_ROOT)))
    assert not missing, f"fichiers sans en-tête SPDX: {missing}"


def test_scope_excludes_tests_and_dashboard():
    paths = {str(f.relative_to(_ROOT)) for f in _first_party_sources()}
    assert not any(p.startswith("tests/") or p.startswith("dashboard/") for p in paths)
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_spdx_headers.py -q`
Expected: FAIL (`test_every_first_party_source_has_spdx_header` : ~85 fichiers sans en-tête).

- [ ] **Step 3 : Insérer les en-têtes (script idempotent, une fois)**

Run ce script (idempotent : ne ré-insère pas si déjà présent dans les 3 premières lignes ; aucun shebang first-party, donc en-tête en ligne 1) :

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
HEADER = "# SPDX-License-Identifier: AGPL-3.0-or-later\n"
root = Path(".")
targets = []
for d in ("core", "coordinator", "agents", "clients"):
    targets += list(root.joinpath(d).rglob("*.py"))
targets.append(root / "server.py")
changed = 0
for f in targets:
    text = f.read_text(encoding="utf-8")
    if any("SPDX-License-Identifier" in ln for ln in text.splitlines()[:3]):
        continue
    f.write_text(HEADER + text, encoding="utf-8")
    changed += 1
print(f"{changed} fichiers modifiés sur {len(targets)}")
PY
```

- [ ] **Step 4 : Lancer les tests + non-régression + surface clean inchangée**

Run:
```bash
.venv/bin/pytest tests/test_spdx_headers.py -q
.venv/bin/pytest -q
.venv/bin/mypy
.venv/bin/ruff check core coordinator/agent_call.py coordinator/proposer.py coordinator/catalog_builder.py coordinator/config.py coordinator/session.py coordinator/loop.py coordinator/app.py coordinator/extractor.py coordinator/assembly.py agents/contracts.py agents/coercion.py agents/manifest.py agents/infer_wiring.py
```
Expected: SPDX test PASS ; suite complète verte (188 avec le nouveau test) ; mypy Success ; ruff « All checks passed! » (les commentaires SPDX ne changent rien à la surface maintenue).

- [ ] **Step 5 : Commit**

```bash
git add -A
git commit -m "chore: en-tetes SPDX AGPL-3.0 sur le code source first-party"
```

Note : `git add -A` est ici volontaire et sûr — le seul changement est l'ajout d'une ligne d'en-tête aux `.py` first-party + le nouveau test ; vérifier `git status` avant commit ne montre que ces fichiers.

---

### Task 2 : `ci.yml` — workflow de test (push/PR)

**Files:**
- Create: `.github/workflows/ci.yml`
- Test: `tests/test_ci_workflow.py`

**Interfaces:**
- Produces: `.github/workflows/ci.yml` — job `test` sur push(main)/pull_request : install `.[dev]`, ruff (surface maintenue), mypy, pytest.

- [ ] **Step 1 : Écrire le test de validation YAML qui échoue**

```python
# tests/test_ci_workflow.py
from pathlib import Path
import yaml

_ROOT = Path(__file__).resolve().parent.parent


def _wf() -> dict:
    return yaml.safe_load((_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))


def _on(wf: dict):
    # PyYAML interprète la clé `on:` comme le booléen True (YAML 1.1).
    return wf.get(True, wf.get("on"))


def test_triggers_push_and_pr():
    on = _on(_wf())
    assert "push" in on and "pull_request" in on


def test_has_test_job_running_gates():
    jobs = _wf()["jobs"]
    assert "test" in jobs
    steps_text = yaml.dump(jobs["test"])
    assert ".[dev]" in steps_text          # install éditable avec extra dev
    assert "ruff check" in steps_text       # gate ruff
    assert "mypy" in steps_text             # gate mypy
    assert "pytest" in steps_text           # gate pytest


def test_ruff_gate_is_scoped_not_whole_repo():
    steps_text = yaml.dump(_wf()["jobs"]["test"])
    # ne doit PAS lancer `ruff check .` (689 findings legacy)
    assert "ruff check ." not in steps_text
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_ci_workflow.py -q`
Expected: FAIL (`.github/workflows/ci.yml` absent).

- [ ] **Step 3 : Créer `.github/workflows/ci.yml`**

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - name: Install
        run: pip install -e ".[dev]"
      - name: Ruff (maintained source surface)
        run: >-
          ruff check
          core
          coordinator/agent_call.py coordinator/proposer.py coordinator/catalog_builder.py
          coordinator/config.py coordinator/session.py coordinator/loop.py
          coordinator/app.py coordinator/extractor.py coordinator/assembly.py
          agents/contracts.py agents/coercion.py agents/manifest.py agents/infer_wiring.py
      - name: Mypy
        run: mypy
      - name: Pytest
        run: pytest -q
```

Note : le gate ruff porte sur la **surface source maintenue** (identique à `[tool.mypy].files`), pas `ruff check .` (dette legacy) ni `tests/` (27 findings legacy dans `tests/core/*`, hors périmètre).

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `.venv/bin/pytest tests/test_ci_workflow.py -q`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add .github/workflows/ci.yml tests/test_ci_workflow.py
git commit -m "ci: workflow de test (ruff surface maintenue, mypy, pytest) sur push/PR"
```

---

### Task 3 : `release.yml` — publication sur tag `v*` (PyPI OIDC + GHCR)

**Files:**
- Create: `.github/workflows/release.yml`
- Test: `tests/test_release_workflow.py`

**Interfaces:**
- Produces: `.github/workflows/release.yml` — sur tag `v*` : `test` → `publish-pypi` (OIDC) + `publish-ghcr` (GITHUB_TOKEN), avec check de cohérence version.

- [ ] **Step 1 : Écrire le test de validation YAML qui échoue**

```python
# tests/test_release_workflow.py
from pathlib import Path
import yaml

_ROOT = Path(__file__).resolve().parent.parent


def _wf() -> dict:
    return yaml.safe_load((_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))


def _on(wf: dict):
    return wf.get(True, wf.get("on"))


def test_triggers_on_version_tags():
    tags = _on(_wf())["push"]["tags"]
    assert any(t.startswith("v") for t in tags)


def test_publish_jobs_need_test():
    jobs = _wf()["jobs"]
    assert "test" in jobs and "publish-pypi" in jobs and "publish-ghcr" in jobs
    assert "test" in jobs["publish-pypi"]["needs"]
    assert "test" in jobs["publish-ghcr"]["needs"]


def test_pypi_uses_oidc_no_token():
    pypi = _wf()["jobs"]["publish-pypi"]
    assert pypi["permissions"]["id-token"] == "write"    # OIDC
    text = yaml.dump(pypi)
    assert "gh-action-pypi-publish" in text
    assert "PYPI_API_TOKEN" not in text                   # pas de secret token
    assert "python -m build" in text


def test_ghcr_pushes_version_and_latest():
    ghcr = _wf()["jobs"]["publish-ghcr"]
    assert ghcr["permissions"]["packages"] == "write"
    text = yaml.dump(ghcr)
    assert "ghcr.io" in text
    assert "GITHUB_TOKEN" in text
    assert ":latest" in text and "ref_name" in text        # version depuis le tag + latest


def test_version_consistency_check_present():
    text = yaml.dump(_wf())
    # un check échoue si le tag != [project].version
    assert "version" in text and ("pyproject" in text or "project" in text)
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_release_workflow.py -q`
Expected: FAIL (`.github/workflows/release.yml` absent).

- [ ] **Step 3 : Créer `.github/workflows/release.yml`**

```yaml
name: release
on:
  push:
    tags: ["v*"]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - name: Check tag matches pyproject version
        run: |
          TAG="${GITHUB_REF_NAME#v}"
          VER=$(python -c "import tomllib,pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])")
          test "$TAG" = "$VER" || { echo "tag $GITHUB_REF_NAME != pyproject version $VER"; exit 1; }
      - name: Install
        run: pip install -e ".[dev]"
      - name: Ruff (maintained source surface)
        run: >-
          ruff check
          core
          coordinator/agent_call.py coordinator/proposer.py coordinator/catalog_builder.py
          coordinator/config.py coordinator/session.py coordinator/loop.py
          coordinator/app.py coordinator/extractor.py coordinator/assembly.py
          agents/contracts.py agents/coercion.py agents/manifest.py agents/infer_wiring.py
      - name: Mypy
        run: mypy
      - name: Pytest
        run: pytest -q

  publish-pypi:
    needs: test
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Build
        run: |
          pip install build
          python -m build
      - name: Publish to PyPI (Trusted Publishing / OIDC)
        uses: pypa/gh-action-pypi-publish@release/v1

  publish-ghcr:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      packages: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build and push (CPU image)
        uses: docker/build-push-action@v6
        with:
          context: .
          file: Dockerfile
          push: true
          tags: |
            ghcr.io/patlegu/cyber-agent-engine:${{ github.ref_name }}
            ghcr.io/patlegu/cyber-agent-engine:latest
```

Note : `github.ref_name` pour un tag `v1.0.0` vaut `v1.0.0` (l'image sera taguée `:v1.0.0` + `:latest`) ; le check de cohérence compare `${GITHUB_REF_NAME#v}` (`1.0.0`) à `[project].version`. Trusted Publishing = aucun secret ; GHCR via `GITHUB_TOKEN` = zéro setup.

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `.venv/bin/pytest tests/test_release_workflow.py -q`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add .github/workflows/release.yml tests/test_release_workflow.py
git commit -m "ci: workflow de release sur tag v* (PyPI OIDC + GHCR), gate par les tests"
```

---

### Task 4 : Documentation « Releases / CI » (bilingue)

**Files:**
- Modify: `README.md`, `README.fr.md`
- Test: `tests/test_readme_release.py`

**Interfaces:** aucune (docs).

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# tests/test_readme_release.py
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_english_readme_documents_releases():
    en = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Trusted Publisher" in en          # setup PyPI OIDC
    assert "ghcr.io" in en                     # image GHCR
    assert "git tag v" in en                   # comment couper une release


def test_french_readme_documents_releases():
    fr = (_ROOT / "README.fr.md").read_text(encoding="utf-8")
    assert "Trusted Publisher" in fr
    assert "ghcr.io" in fr
    assert "git tag v" in fr
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `.venv/bin/pytest tests/test_readme_release.py -q`
Expected: FAIL (sections absentes).

- [ ] **Step 3 : Ajouter la section anglaise à `README.md`**

Après la section « Operations » (ou avant « License »), ajouter :

````markdown
### Releases & CI

- **CI** (`.github/workflows/ci.yml`): on every push to `main` and every pull
  request, runs ruff (maintained source surface), mypy, and the full test suite.
- **Release** (`.github/workflows/release.yml`): pushing a `v*` tag runs the test
  gate, then publishes the sdist+wheel to **PyPI** (Trusted Publishing / OIDC — no
  stored token) and a CPU Docker image to **GHCR**
  (`ghcr.io/patlegu/cyber-agent-engine:<tag>` + `:latest`).
- **One-time PyPI setup:** create a **Trusted Publisher** on PyPI for project
  `cyber-agent-engine` (owner `patlegu`, repo `cyber-agent-engine`, workflow
  `release.yml`, environment `pypi`). GHCR needs no setup (uses `GITHUB_TOKEN`).
- **Cutting a release:** align `[project].version` in `pyproject.toml`, then
  `git tag vX.Y.Z && git push origin vX.Y.Z` (the tag must equal the version or the
  release job fails).
- The GHCR image is the **CPU** variant; the GPU image is a local build
  (`Dockerfile.gpu`).
````

- [ ] **Step 4 : Ajouter la section française à `README.fr.md`**

Après la section « Exploitation » (ou avant « Licence »), ajouter :

````markdown
### Releases & CI

- **CI** (`.github/workflows/ci.yml`) : à chaque push sur `main` et chaque pull
  request, lance ruff (surface source maintenue), mypy et la suite de tests.
- **Release** (`.github/workflows/release.yml`) : pousser un tag `v*` lance le gate
  de tests puis publie le sdist+wheel sur **PyPI** (Trusted Publishing / OIDC —
  aucun token stocké) et une image Docker CPU sur **GHCR**
  (`ghcr.io/patlegu/cyber-agent-engine:<tag>` + `:latest`).
- **Setup PyPI (une fois)** : créer un **Trusted Publisher** sur PyPI pour le projet
  `cyber-agent-engine` (propriétaire `patlegu`, dépôt `cyber-agent-engine`, workflow
  `release.yml`, environnement `pypi`). GHCR ne nécessite rien (`GITHUB_TOKEN`).
- **Couper une release** : aligner `[project].version` dans `pyproject.toml`, puis
  `git tag vX.Y.Z && git push origin vX.Y.Z` (le tag doit égaler la version, sinon
  le job de release échoue).
- L'image GHCR est la variante **CPU** ; l'image GPU est un build local
  (`Dockerfile.gpu`).
````

- [ ] **Step 5 : Lancer + suite complète**

Run: `.venv/bin/pytest tests/test_readme_release.py -q && .venv/bin/pytest -q`
Expected: PASS ; suite complète verte.

- [ ] **Step 6 : Commit**

```bash
git add README.md README.fr.md tests/test_readme_release.py
git commit -m "docs: section Releases & CI (PyPI OIDC, GHCR, tag v*) bilingue"
```

---

## Auto-revue du plan (checklist auteur)

**Couverture du spec :**
- Chantier 1 (SPDX first-party + enforcement) → Task 1. ✅
- Chantier 2 (`ci.yml`) → Task 2. ✅
- Chantier 3 (`release.yml` PyPI OIDC + GHCR + check version) → Task 3. ✅
- Documentation (Releases/CI bilingue) → Task 4. ✅
- Tests (enforcement SPDX, validation `ci.yml`/`release.yml`, non-régression) → Tasks 1-4. ✅

**Décisions actées reflétées** : PyPI Trusted Publishing OIDC (pas de token) ; GHCR via `GITHUB_TOKEN` ; SPDX sur source first-party (pas tests/dashboard) ; gate ruff sur la surface maintenue (pas `ruff check .` ni `tests/`).

**Piège YAML géré** : les tests lisent la clé `on:` via `wf.get(True, wf.get("on"))` (PyYAML parse `on` en booléen `True`).

**Placeholders** : aucun — workflows et sections doc fournis in extenso ; le script SPDX est idempotent et complet.

**Point d'attention** : Task 1 utilise `git add -A` (seul l'ajout d'en-têtes + le nouveau test sont en jeu) ; vérifier `git status` avant commit. Le check de version dans `release.yml` requiert `tomllib` (Python 3.11, présent sur le runner setup-python 3.11).

**Dette reportée** : nettoyage ruff legacy (dépôt entier + `tests/core/*`) ; protection de branche GitHub (manuel) ; matrix multi-Python ; signature/SBOM ; multi-tenant (D3c) ; i18n (D3d).
