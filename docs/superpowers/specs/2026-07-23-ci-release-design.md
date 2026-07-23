# Design — CI de release & en-têtes SPDX (sous-projet D3b)

Date : 2026-07-23
Dépôt : `cyber-agent-engine` (public)
Statut : validé pour implémentation

## Contexte et cadrage

A→D3a sont livrés et mergés : le produit est lançable, portable, licencié AGPL,
packageable (wheel vérifié), dockerisé (CPU+GPU), documenté (EN/FR), à audit borné
et multi-serveur. D2 a **différé la publication réelle** (PyPI/GHCR) et les
**en-têtes SPDX par fichier** à D3b. D3b outille la **release automatisée** et la
**hygiène de licence par fichier**.

**Décomposition de D3 (rappel) :** D3a (durcissement, livré), **D3b — CI de
release** *(ce spec)*, D3c (multi-tenant, possiblement YAGNI), D3d (i18n runtime).

### État constaté

- **Aucune CI** (`.github/workflows` absent).
- **`mypy` vert** (scopé via `[tool.mypy].files`, 33 fichiers).
- **`ruff check .` (dépôt entier) → ~689 findings** (dette legacy : `agents/*`,
  `server.py`, `dashboard/`). Le gating ruff du projet porte sur la **surface
  first-party maintenue** (décisions A→D), pas le dépôt entier.
- **85 fichiers `.py` first-party** (core/coordinator/agents/clients + server.py +
  racine), sans en-tête SPDX.
- `LICENSE` (AGPL-3.0) et `pyproject` `license = "AGPL-3.0-or-later"` en place (D2).

### Décisions actées

- **PyPI : Trusted Publishing (OIDC)** — aucun secret long-terme ; setup manuel
  côté PyPI (*pending publisher*).
- **GHCR : `GITHUB_TOKEN`** — zéro setup.
- **SPDX : sur le code source first-party** (pas tests/dashboard) + test
  d'enforcement.

**Contrainte structurante** : les workflows GitHub Actions ne s'exécutent pas en
test local → les « tests » de D3b sont **statiques** (validation YAML + enforcement
SPDX + non-régression). Les workflows sont **commités mais inertes** jusqu'à un tag
`v*` / la configuration du trusted publisher.

## Contrainte gouvernante — CQI > 9

Test-first (tests statiques déterministes), non-régression des 187 tests A→D3a.
La CI gate sur la **surface first-party maintenue** (pas `ruff check .`). Commits
`type(scope): sujet` minuscules, sans emoji, sans `Co-Authored-By` ni mention d'IA.
Docstrings/commentaires de code en français ; documentation utilisateur bilingue.

## Chantier 1 — En-têtes SPDX (code source first-party)

- **Contenu** : première ligne de code de chaque fichier source first-party =
  `# SPDX-License-Identifier: AGPL-3.0-or-later`, placée **après un shebang**
  éventuel (`#!...`), sinon tout en haut, **avant** le docstring de module. Pas de
  bloc copyright verbeux (l'identifiant SPDX suffit).
- **Périmètre** : `.py` sous `core/`, `coordinator/`, `agents/`, `clients/`, plus
  `server.py` et les `.py` racine first-party. **Exclus** : `tests/`, `dashboard/`,
  `.venv/`.
- **Insertion** : script déterministe **idempotent** (ne ré-insère pas si présent).
  Un commentaire SPDX n'ajoute aucune anomalie ruff/mypy — surface clean inchangée,
  dette legacy inchangée.
- **Enforcement** : `tests/test_spdx_headers.py` énumère le périmètre **par motif**
  (répertoires first-party, pas une liste figée) et **échoue** si un fichier n'a pas
  l'en-tête dans ses premières lignes → garde-fou permanent pour les futurs fichiers.
- **Cohérence D2** : l'identifiant par fichier correspond exactement à l'expression
  pyproject et au fichier `LICENSE`.

## Chantier 2 — `ci.yml` (test sur push/PR)

- **Déclencheurs** : `push` sur `main` + `pull_request`.
- **Job `test`** (`ubuntu-latest`, Python 3.11 via `actions/setup-python`, cache
  pip) :
  1. `pip install -e ".[dev]"` (core + build + pytest ; pas `[gpu]`).
  2. **`ruff check`** sur la **surface maintenue** (liste de chemins first-party
     clean, figée au plan et vérifiée verte ; **pas** `ruff check .`).
  3. **`mypy`** (périmètre `[tool.mypy].files`).
  4. **`pytest -q`** (les 187 tests ; certains construisent un wheel via `build`).
- Chaque étape est bloquante. Pas de matrix multi-version (cible 3.11 ; extensible).
- La dette ruff legacy (dépôt entier) est **hors périmètre**, documentée.

## Chantier 3 — `release.yml` (publication sur tag `v*`)

Déclencheur : `push` de tag `v*`. Trois jobs.

- **`test`** : réutilise le gate de `ci.yml` (install `.[dev]` → ruff surface /
  mypy / pytest). Les jobs de publication `needs: test` → **aucune release si les
  tests échouent** (fail-closed).
- **`publish-pypi`** (`needs: test`) : `permissions: { id-token: write }`,
  `environment: pypi` ; `python -m build` → `dist/*` ; `pypa/gh-action-pypi-
  publish@release/v1` (**Trusted Publishing OIDC, aucun token**).
- **`publish-ghcr`** (`needs: test`) : `permissions: { packages: write, contents:
  read }` ; `docker/login-action` vers `ghcr.io` avec `github.actor` +
  `secrets.GITHUB_TOKEN` ; `docker/build-push-action` build le **`Dockerfile` CPU**
  et pousse `ghcr.io/patlegu/cyber-agent-engine:<version>` **et** `:latest`. La
  version dérive de `github.ref_name` (sans le `v`).
- **Cohérence version** : un check en tête de `test` (ou publish) échoue si le tag
  `vX.Y.Z` ≠ `[project].version` du pyproject (évite une release incohérente).
- L'image GPU (`Dockerfile.gpu`) reste un build local documenté, hors CI.
- Le workflow est **inerte** tant qu'aucun tag `v*` n'est poussé.

## Tests et qualité

Déterministes, sans exécuter les workflows :

1. **Enforcement SPDX** (`tests/test_spdx_headers.py`) : tout `.py` first-party
   contient l'en-tête ; échoue sur un manquant.
2. **`ci.yml`** (`tests/test_ci_workflow.py`, YAML parse) : triggers push/PR ; job
   `test` ; étapes install `.[dev]` + ruff + mypy + pytest présentes.
3. **`release.yml`** (`tests/test_release_workflow.py`, YAML parse) : trigger tag
   `v*` ; jobs `test`/`publish-pypi`/`publish-ghcr` ; `publish-*` ont `needs:
   test` ; `publish-pypi` a `id-token: write` (OIDC, pas de token secret) ;
   `publish-ghcr` a `packages: write` et pousse `:latest` + version ; check de
   cohérence version présent.
4. **Non-régression** : les 187 tests A→D3a restent verts ; `ruff` surface
   maintenue + `mypy` verts (les en-têtes SPDX n'ajoutent rien).

## Documentation

README (EN + FR) — section « Releases / CI » :

- CI (test sur push/PR) ; release sur tag `v*` (PyPI + GHCR).
- **Setup manuel** : configurer le *Trusted Publisher* PyPI (projet
  `cyber-agent-engine`, repo, workflow `release.yml`, environnement `pypi`) ; GHCR
  ne nécessite rien.
- Couper une release : aligner `[project].version` puis
  `git tag vX.Y.Z && git push origin vX.Y.Z`.
- Note : image GHCR = variante CPU ; GPU = build local (`Dockerfile.gpu`).

## Dette reportée / hors périmètre

- Nettoyage de la dette ruff legacy (dépôt entier) — chantier séparé si souhaité.
- Protection de branche GitHub (réglage manuel côté dépôt), matrix multi-Python,
  signature d'artefacts/SBOM/attestations — ultérieurs.
- Multi-tenant → **D3c** ; i18n runtime → **D3d**.

## Hors périmètre

- Modification du code applicatif A/B/C/D (hors ajout des en-têtes SPDX, purement
  des commentaires).
- Refonte du dashboard web.
