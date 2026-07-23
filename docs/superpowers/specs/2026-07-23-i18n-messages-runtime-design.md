# Design — i18n des messages runtime (sous-projet D3d)

Date : 2026-07-23
Dépôt : `cyber-agent-engine` (produit runtime, public)
Statut : validé pour implémentation

## Contexte et cadrage

A→D3b sont livrés et mergés : le produit trust-cored est lançable, portable, licencié
AGPL, packageable, dockerisé, à CI de release. Les messages runtime destinés aux
opérateurs (exceptions levées, logs, sorties CLI/serveur) sont aujourd'hui **en
français**. Pour un produit AGPL public **déployable par des tiers non-francophones**,
D3d les normalise en **anglais canonique**.

**Décomposition de D3 (rappel) :** D3a (durcissement, livré), D3b (CI de release, livré),
D3c (multi-tenant — **écarté, YAGNI** pour un self-hosted mono-opérateur), **D3d — i18n
des messages runtime** *(ce spec)*.

### Décisions actées (brainstorming)

- **Périmètre = messages opérateur uniquement** : exceptions, logs, CLI/serveur.
  **Exclus** : docstrings (FR, convention), commentaires (FR, convention), descriptions
  de fonctions/outils LLM (`"description"` — couplées aux LoRA entraînés → sous-chantier
  **D3d-bis** ultérieur, après évaluation de l'impact entraînement), documentation
  utilisateur (reste bilingue EN/FR).
- **Stratégie = normalisation en dur (anglais), inline** : traduction directe dans le
  code, pas d'infra i18n (pas de gettext, pas de catalogue, pas de sélection de locale).
  Colle au style actuel (chaînes inline), YAGNI pour un besoin « canonique anglais ».
- **Garde-fou = test AST** sur les appels `raise` / `logging.*` / `print` : échoue si un
  caractère accentué FR apparaît dans leurs littéraux chaîne. Backstop de non-régression,
  dans l'esprit du test d'enforcement SPDX (D3b).

### État constaté (mesuré via AST sur la surface first-party)

- **~211 sites** de message opérateur contenant un accent FR : **18 `raise`** (dont le
  `HTTPException(detail=…)` du serveur, passé en **mot-clé**) + **193 logs** + **0
  `print`**.
- Répartition : concentrée dans `agents/opnsense/*` (~150) et `clients/` (dont
  `wireguard_linux_client.py`, 13) ; `core/`+`coordinator/`+`server.py` ~une douzaine.
- **Couplage tests** : quelques tests assertent sur le texte FR d'un message runtime
  (ex. `tests/coordinator/test_proposer.py` : `assert prop.summary == "terminé"`). Le
  sweep doit co-mettre à jour ces assertions.
- Le français **sans accent** existe aussi (« timeout serveur ») : non détecté par le
  garde-fou, capté par le sweep (voir Limite connue).

## Contrainte gouvernante — CQI > 9

Test-first (garde-fou AST déterministe), non-régression des 201 tests A→D3b. Traduction
technique fidèle. Docstrings et commentaires FR **inchangés** ; documentation utilisateur
bilingue **inchangée**. Commits `type(scope): sujet` minuscules, sans emoji, sans
`Co-Authored-By` ni mention d'IA.

## Chantier 1 — Sweep de traduction (messages opérateur → anglais)

- **Cibles** : les littéraux chaîne passés à
  - `raise <Exc>(…)` — arguments **positionnels et mots-clés** (ex. `detail=`),
  - appels de log — méthodes `debug/info/warning/warn/error/critical/exception/log`
    (sur `logger`, `logging`, `log`),
  - `print(…)`,

  sur `core/`, `coordinator/`, `agents/`, `clients/`, `server.py`.
- **Préservation** : interpolations f-string, spécificateurs de format (`%s`,
  `%(name)s`), et préfixes-tags structurants (`[OPNsense]`, `[Stormshield]`, …). Seul le
  texte lisible passe en anglais ; la structure du message est conservée.
- **Traduction** : vocabulaire technique fidèle (« règle » → *rule*, « aucun agent
  découvert sur les serveurs d'agents » → *no agent discovered on the agent servers*,
  « absent : le coordinateur refuse de démarrer » → *missing: the coordinator refuses to
  start*, …). Le français **sans accent** rencontré dans une cible est traduit aussi.
- **Tests couplés** : pour chaque message traduit, mettre à jour tout test qui asserte
  sur l'ancien texte FR (repérage par grep du texte avant traduction).
- **Hors cible** : docstrings, commentaires, dicts `"description"` LLM — **non modifiés**.

## Chantier 2 — Garde-fou AST (non-régression)

- **Fichier** : `tests/test_runtime_messages_english.py`.
- **Mécanique** : parse chaque `.py` de la surface first-party via `ast` ; collecte les
  littéraux str (y compris parties constantes des f-strings / `JoinedStr`) des **args +
  kwargs** des nœuds `Raise` (appel d'exception), des appels dont la méthode ∈
  `{debug,info,warning,warn,error,critical,exception,log}`, et des appels `print` ;
  **échoue** en listant tout littéral contenant un caractère de l'ensemble accentué FR
  `éèàçêîôûïœ` + majuscules + `ëüö`.
- **Portée par construction** : n'inspecte **que** ces trois catégories d'appels → ne
  touche jamais docstrings ni dicts `"description"`. Non-vacuité : retirer une traduction
  (remettre un message accentué) fait rougir le test.
- **Périmètre de fichiers** : `core/ coordinator/ agents/ clients/` (rglob) + `server.py`
  (mêmes répertoires que la surface maintenue ; énumération **par motif**, pas liste
  figée → futurs fichiers couverts).

## Découpage (indicatif, pour le plan)

Par couche, chaque tâche testable seule ; **garde-fou en dernier** (pas de xfail
temporaire) :

- **T1** : `core/` + `coordinator/` + `server.py` (~une douzaine de sites) + tests
  couplés.
- **T2** : `clients/` (~20 sites).
- **T3** : `agents/` hors opnsense (base, anony, crowdsec, wireguard, pfsense,
  stormshield, router, ner, classifier…).
- **T4** : `agents/opnsense/*` (~150 sites sur ~15 sous-modules).
- **T5** : garde-fou `tests/test_runtime_messages_english.py` — doit être **vert
  d'emblée** (tous les sweeps faits) ; prouver la non-vacuité.

## Tests et qualité

Test-first, déterministes :

1. **Garde-fou AST** (T5) : vert sur la surface nettoyée ; non-vacuité démontrée.
2. **Non-régression** : les 201 tests A→D3b restent verts ; assertions FR couplées mises
   à jour avec leur message (chaque tâche laisse la suite verte).
3. **Périmètre préservé** : docstrings/commentaires FR et descriptions LLM **non
   modifiés** (vérifiable : le diff ne touche que des args de raise/log/print).

## Documentation

Aucune section README nouvelle requise (changement interne). Note brève possible dans le
CHANGELOG/README (« runtime operator messages are in English ») — **optionnelle**, à
décider au plan ; pas de refonte doc.

## Limite connue (documentée)

Le garde-fou basé sur les **accents** ne détecte pas le français **sans accent**
(« timeout serveur »). Le **sweep** est le mécanisme de complétude ; le garde-fou est le
filet anti-régression du cas courant (accentué) — choix assumé (test AST accents, pas la
variante liste-de-mots, plus bruyante). Documenté dans le docstring du test.

## Dette reportée / hors périmètre

- **D3d-bis** : traduction des descriptions de fonctions/outils LLM (`"description"`),
  après évaluation de l'impact sur l'inférence des LoRA entraînés.
- Vraie infra i18n (gettext, locales commutables) — non retenue (YAGNI).
- Détection du français sans accent (liste de mots) — non retenue (bruit).

## Hors périmètre

- Modification du cœur de confiance au-delà de la traduction des messages (purement des
  chaînes).
- Descriptions LLM, docstrings, commentaires, documentation utilisateur.
- Refonte du dashboard web.
