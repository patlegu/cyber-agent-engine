# Design — Vitrine blog : série d'articles cyber-agent-engine

Date : 2026-07-23
Sujet : `cyber-agent-engine` (produit runtime, dépôt public GitHub AGPL)
Publication : blog Hugo **nope** (`/srv/__NOPE__/nope.breizhland.eu`, gitlab `web_group_repo/nope.breizhland.eu`, `nope.breizhland.eu`)
Statut : validé pour implémentation

## Contexte et objectif

Créer une **vitrine** de `cyber-agent-engine` — coordinateur multi-agents de
sécurité réseau à **cœur de confiance**, produit AGPL déployable par des tiers —
sous forme d'une **série d'articles** sur le blog technique existant.

**Audience / but (acté)** : **crédibilité technique / portfolio** — pairs
ingénieurs, recruteurs, communauté DevSecOps. Ingénierie en profondeur, ton
technique, **pas de CTA commercial**. Continuité du registre du blog.

Le blog couvre déjà la lignée du projet (`Blog/Agents_en_Production/` :
migration Qwen2.5, CAP v1, multi-LoRA ; `IA/opnsense_llm_in_firewall/` :
approche in-box ; `Blog/victor_le_nettoyeur/` : AnonyNER). `cyber-agent-engine`
est **la suite logique** : le produit trust-cored qui émerge de ces expériences.

## Décisions actées (brainstorming)

- **Série dédiée** `series: ["cyber-agent-engine"]` (pas d'extension d'une série
  existante), avec liens croisés vers les articles existants.
- **Angle A + mix** : squelette « architecture de confiance » (chaque article =
  un pilier du cœur de confiance), avec le **récit** en ouverture (évolution
  in-box → externe) et la **profondeur code** à l'intérieur de chaque article.
- **6 articles** (5 piliers + 1 méta sur la méthode de construction).
- **Bilingue FR + EN en séries parallèles, FR d'abord** : pas de multilingue
  Hugo natif (le blog n'en a pas) → posts parallèles. **FR canonique/rédigé en
  premier**, **miroir EN** ensuite. Lien croisé inline en tête d'article.
- **Le dépôt GitHub pointera vers la version EN** (lien deep-dive/write-up dans
  le README de `cyber-agent-engine`, ajouté quand l'EN est en ligne).

## Contrainte gouvernante — exactitude & sûreté

Leçon de l'audit README : **toute affirmation technique est vérifiée contre le
code** du dépôt public `cyber-agent-engine` (fichiers, fonctions, variables
d'env exactes) — pas d'invention, pas de sur-promesse. **Zéro secret** : aucun
token/clé/`.env` déchiffré ; les exemples utilisent des placeholders. Contenu
issu **uniquement du dépôt public GitHub AGPL** (rien de la factory GitLab
privée). Code extrait = fidèle au dépôt (chemins réels).

## Structure et conventions de la série

### Emplacement (dépôt blog nope)

- **FR** : `content/post/IA/cyber-agent-engine/<N-slug>/index.md` (page bundles).
- **EN** : `content/post/AI/cyber-agent-engine/<N-slug>/index.md`.
- Catégorie `IA` (FR) / `AI` (EN) ; `series: ["cyber-agent-engine"]` des deux
  côtés ; `series_order` = 1→6.

### Frontmatter type (aligné sur l'existant)

```yaml
---
title: '<titre narratif>'
title_image: "/img/<bannière>.png"   # bannière de série commune ou par article
categories: [IA]                       # [AI] côté EN
tags: [IA, Sécurité, LLM, DevSecOps, OPNsense, "trust core"]
date: 2026-0X-XX
mermaid: true
no_toc: false
draft: true                            # bascule false à la publication
url: "cae-<N>-<slug>"                  # FR ; EN = "cae-<N>-<slug>-en"
series: ["cyber-agent-engine"]
series_order: <N>
---
```

- **`url:` fixes** (slugs stables) → l'article FR peut poser le lien vers l'URL
  EN **avant** que l'EN soit publié.
- **Lien croisé** en tête : FR → « 🇬🇧 [English version](/cae-<N>-<slug>-en/) » ;
  EN → « 🇫🇷 [Version française](/cae-<N>-<slug>/) » (posé quand la paire existe).
- **1 schéma mermaid** par article (langue-neutre : seuls les libellés se
  traduisent). Code en fences (coloration chroma du thème).
- Calibrage : **~1500–2500 mots/article**, 1 thèse forte + code réel + 1 mermaid
  + liens croisés vers les articles existants du blog.

### Rollout

- **Vague 1** : les 6 articles **FR en `draft: true`** → relecture opérateur →
  publication (`draft: false` + build/déploiement Hugo, hors périmètre).
- **Vague 2** : **miroir EN** (traduction de la prose ; code/mermaid
  relabellisés — pas de re-travail d'ingénierie).
- **Post-EN** : ajouter le lien deep-dive → série EN dans le README de
  `cyber-agent-engine`.

## Découpage des 6 articles

Chaque fiche : thèse · plan · **ancres de code réelles** (à extraire du dépôt) ·
schéma · liens. Les slugs `url:` sont fixés ici (stabilité des liens croisés).

### Article 1 — « Un LLM avec les droits d'admin sur ton firewall : comment ne pas se faire pwn »
`url: cae-1-llm-firewall-trust-core` · `series_order: 1`
- **Thèse (ouverture, récit)** : automatiser la sécurité réseau avec un LLM est
  puissant *et* terrifiant — injection de prompt, action destructrice
  hallucinée, fuite de PII vers le modèle, absence d'audit. Des expériences
  in-box à la nécessité d'un cœur de confiance.
- **Contenu** : le problème ; les 5 principes (fail-closed, moindre privilège,
  humain dans la boucle, jetons-only, auditable) ; vue d'ensemble.
- **Code/ancres** : `core/` (arborescence : `policy/`, `approval/`, `audit/`,
  `tokens/`, `execution/`, `decision.py`, `orchestrator.py`).
- **Mermaid** : opérateur → coordinateur[cœur de confiance] → agents → équipements.
- **Liens** : `opnsense_llm_in_firewall`, `Agents_en_Production`.

### Article 2 — « Le LLM ne voit que des jetons »
`url: cae-2-llm-sees-only-tokens` · `series_order: 2`
- **Thèse** : le LLM de raisonnement ne voit jamais IP/hostname/secret réels —
  uniquement des jetons ; le vault dé-tokenise **à la frontière d'exécution**.
- **Contenu** : pourquoi (rayon de souffle d'une injection, souveraineté — aucune
  PII vers OpenRouter/Anthropic, audit token-only).
- **Code/ancres** : `core/tokens/vault.py`, `coordinator/extractor.py`.
- **Mermaid** (séquence) : requête → tokenize → LLM propose sur jetons → vault
  détokenize → exécute.
- **Liens** : `victor_le_nettoyeur` (AnonyNER).

### Article 3 — « Refuser par défaut »
`url: cae-3-deny-by-default` · `series_order: 3`
- **Thèse** : politique **fail-closed** (deny par défaut) + **gate d'approbation
  humaine** fail-closed.
- **Contenu** : catalogue de capacités ; `core.decide`
  (valider→évaluer→auditer→verdict) ; `GatedLoop` ; approbation `resume`/`reject`
  ; `session_ttl`.
- **Code/ancres** : `core/policy/engine.py`, `core/decision.py`,
  `core/approval/store.py`, `coordinator/loop.py`, endpoints
  `/coordinator/resume|reject` (`coordinator/app.py`).
- **Mermaid** : propose → decide → {allow: exec | approve: suspend→humain→
  resume/reject | deny: stop}.

### Article 4 — « Hors de la boîte »
`url: cae-4-off-box` · `series_order: 4`
- **Thèse (contraste + portabilité)** : pourquoi le LLM doit vivre **hors** de
  l'équipement. In-box (OAF : surface d'attaque, contention CPU, cycle de vie,
  audit) vs coordinateur externe.
- **Contenu** : portabilité — core **sans GPU**, backends
  (anthropic/openai-compatible/vllm/ollama), découplage factory ; l'agent cible
  l'API OPNsense **sur le LAN** (interop documentée).
- **Code/ancres** : `coordinator/llm/`, `clients/opnsense_api_client.py`,
  variables `OPNSENSE_*`, README section « Targeting a real OPNsense (interop) ».
- **Mermaid** : topologie de déploiement (coordinateur hors-boîte sur le LAN →
  API OPNsense).
- **Liens** : `opnsense_llm_in_firewall`.

### Article 5 — « Assembler et exploiter en confiance »
`url: cae-5-assemble-operate-trust` · `series_order: 5`
- **Thèse** : passer de « ça marche » à « déployable par des tiers ».
- **Contenu** : `create_default_app` ; `FileAuditSink` (rotation bornée, audit
  token-only) ; multi-serveur (`AGENT_SERVERS`, collision fail-closed) ;
  Docker/compose ; licence AGPL ; CI de release (SPDX, PyPI OIDC, GHCR) ;
  garde-fous AST.
- **Code/ancres** : `coordinator/app.py::create_default_app`,
  `core/audit/file_sink.py`, `coordinator/assembly.py`, `docker-compose.yml`,
  `.github/workflows/`.
- **Mermaid** : topologie compose / pipeline CI.

### Article 6 — « Comment on l'a construit » (méta)
`url: cae-6-how-it-was-built` · `series_order: 6`
- **Thèse (process)** : la rigueur comme livrable — développement piloté par
  sous-agents, revue adversariale, test-first.
- **Contenu** : boucle SDD (Superpowers) ; revue par tâche + revue finale ;
  garde-fous AST (SPDX, i18n, cohérence surface lint) ; objectif CQI>9 ;
  décomposition en sous-projets A→D3d.
- **Code/ancres** : `tests/test_spdx_headers.py`,
  `tests/test_runtime_messages_english.py`,
  `tests/test_lint_surface_consistency.py`, `docs/superpowers/specs/`.
- **Mermaid** : la boucle SDD (implémenteur → revue → fix → revue finale → merge).

## Tests et qualité (relecture éditoriale)

Il n'y a pas de tests automatisés (contenu prose). La qualité est assurée par :

1. **Exactitude** : chaque affirmation/extrait de code re-vérifié contre le
   dépôt `cyber-agent-engine` avant publication (relecture dédiée, comme la
   revue anti-« mensonge » de l'audit README).
2. **Zéro secret** : aucun secret déchiffré dans les articles ; placeholders
   uniquement.
3. **Cohérence de série** : `series_order` continu, liens croisés valides
   (FR↔EN et vers les articles existants), frontmatter conforme.
4. **Rendu** : mermaid valide (le blog a `mermaid: true`), code en fences,
   `draft: true` jusqu'à validation.

## Hors périmètre

- Le **miroir EN** (vague 2) et le lien README→série EN : planifiés, exécutés
  après la vague FR.
- Le build/déploiement Hugo (process opérateur habituel).
- La factory GitLab privée (entraînement/LoRA) : hors sujet, le produit seul est
  la vitrine.
- Toute modification du blog au-delà de l'ajout des articles (pas de multilingue
  Hugo natif, pas de refonte de thème).
- Les 6 fichiers en cours de modification non committés du dépôt blog : ne pas y
  toucher.

## Dette / suites

- Vague 2 (EN) et lien README.
- Éventuel `title_image` par article (visuel) si une bannière commune ne suffit
  pas — non bloquant.
