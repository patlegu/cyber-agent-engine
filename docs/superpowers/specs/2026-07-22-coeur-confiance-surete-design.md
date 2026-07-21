# Design — Cœur de confiance & sûreté (sous-projet A)

Date : 2026-07-22
Dépôt : `cyber-agent-engine` (public)
Statut : validé pour implémentation

## Contexte et cadrage

`cyber-agent-engine` est un coordinateur multi-agents où un LLM planifie des
actions et les délègue à des agents-outils qui pilotent de **vrais** équipements
(OPNsense, WireGuard, CrowdSec). Un audit (2026-07-22, `docs/audit-2026-07.md`)
a révélé des défauts structurels de confiance : routes sans authentification,
Judge *fail-open*, AnonyNER qui **n'anonymise pas** et valeurs sensibles loguées
puis exposées, garde d'approbation asymétrique, zéro test.

**Finalité actée** : faire de ce projet un **produit déployable par des tiers**
(barre la plus haute — sécurité par défaut, garde-fous que l'opérateur ne
contrôle pas à l'exécution). Cette finalité dépasse un seul spec ; le travail est
donc **décomposé** :

- **A — Cœur de confiance & sûreté** *(ce spec)* : moteur de politique
  déterministe fail-closed, auth sans faille, frontière d'exécution, tokenisation
  des valeurs sensibles.
- **B — Contrat coordinateur↔agents (CAP v2)** : schéma validé, typé, borné,
  porteur des métadonnées de risque. Dépend de A.
- **C — Portabilité modèles & runtime** : découpler des LoRA fine-tunés et de
  l'hypothèse GPU.
- **D — Packaging, licence, exploitation, isolation/multi-tenant**.

Ce spec ne couvre que **A**. C'est un **redesign dans le code existant** : la
couche `clients/` (qualité référence à l'audit) est conservée ; c'est la chaîne
de confiance au-dessus qui est refondue.

## Contrainte gouvernante — CQI > 9 dès le départ

Règle opérateur durable : qualité de code visée **> 9/10, atteinte à la
conception, pas en rétrofit**. A est donc **conçu** pour l'atteindre et livré
**test-first** :

- DAG de modules sans cycle, feuilles **pures** composées par un cœur mince ;
- la logique de sécurité vit dans des **fonctions pures** (seams de test triviaux) ;
- les gardes sont des **types** (mypy strict = gardien), pas des vérifications
  runtime éparses ;
- chaque anti-pattern nommé par l'audit (fail-open, god function, `except` large,
  secret en dur) a son contre-test ;
- cible mesurée par une passe `cli-audit-code` avant clôture.

## Modèle de contrôle (décision cardinale)

**L'IA propose, une politique déterministe + l'humain disposent.** Le LLM n'a
**jamais** le dernier mot sur une mutation. Défaut **fail-closed**. C'est l'inverse
de l'architecture actuelle (ReAct qui auto-exécute, Judge optionnel/fail-open).

## Architecture & DAG de modules

Principe : un **point de passage obligé unique, infranchissable par
construction**. Rien n'atteint un équipement sans un verdict `allow` (ou `approve`
résolu par un humain).

```
Requête (authentifiée)
  → Coordinateur : le LLM planifie sur un contexte TOKENISÉ
  → le LLM émet une Intention (typée, validée par schéma)     ← proposition seule
  → Moteur de politique : evaluate(intention, policy) → Verdict     ← fonction PURE
        deny    → stop + audit
        approve → checkpoint humain (hors-bande) → continue ou stop
        allow   → continue
  → Frontière d'exécution : détokenise → appel tool-agent (CAP validé) → équipement
  → audit (jetons uniquement)
```

**DAG (dépendances, sans cycle)** :

- `policy/` — **pur** : `Intention`, `Rule`, `Verdict`, `evaluate()`. Ne dépend que
  de Pydantic. Défaut deny. Entièrement unit-testable.
- `tokens/` — bijection **par session** : `tokenize`/`detokenize`. Dépend de
  l'extracteur NER. Aucun I/O.
- `auth/` — vérification + dépendance FastAPI unique, appliquée à **toute** route.
  Feuille.
- `execution/` — la frontière : prend un verdict **autorisé** + le détokeniseur,
  appelle `clients/`. Dépend de `policy`, `tokens`, `clients`.
- `audit/` — puits append-only, jetons seulement. Feuille.
- **coordinateur** — orchestre (LLM propose → policy → humain → execution). Dépend
  de tout ce qui précède ; rien ne dépend de lui.

Feuilles pures composées par un cœur mince → 80 % de la surface critique testable
sans infra.

## Moteur de politique

### Types (purs)

```
Intention:
  capability: str        # "namespace.fonction", ex. "opnsense.add_nat_port_forward"
  args: dict[str, Token] # arguments, valeurs déjà tokenisées
  rationale: str         # justification LLM — audit/humain, JAMAIS décisionnelle

Rule:                    # données, versionnables par l'opérateur
  match: {capability: glob, args: {clé: condition}}  # conditions structurelles seulement
  effect: allow | approve | deny
  reason: str

Verdict:
  effect: allow | approve | deny
  matched_rule: Rule | None    # None ⟺ deny par défaut
  intention: Intention
```

- `capability` doit exister dans le **catalogue de capacités** (voir plus bas) ;
  `args` typés selon la signature de la capacité. Intention malformée → rejetée
  **avant** la politique.
- Les `condition` ne comparent que des **structures** (glob, égalité, appartenance,
  absence) — **jamais d'exécution de code**. Exemple de finesse :
  `opnsense.add_nat_port_forward` → `approve`, mais `deny` si `args.interface == "wan"`.

### `evaluate(intention, policy) -> Verdict` — pure, déterministe

- première règle qui matche gagne (ordre = priorité explicite, comme un firewall) ;
- **aucune règle ne matche → `deny`** (fail-closed, point cardinal) ;
- le verdict porte l'`effect`, la `Rule` déclenchante (traçabilité) et l'`Intention`.

### Invariants

- **Le LLM ne peut pas s'auto-autoriser** : son `rationale` et tout champ
  « requires_approval » qu'il produirait sont **ignorés** par `evaluate`. (On
  généralise en invariant le bon réflexe déjà présent dans `_needs_approval`, qui
  ignore l'avis du LLM.)
- La politique est un **artefact de l'opérateur**, chargé et **validé au
  démarrage** (règle mal formée, capacité inconnue → le serveur ne démarre pas,
  plutôt que de dégrader en silence).

### Catalogue de capacités

Aujourd'hui découvert dynamiquement via `GET /capabilities`. Pour que `evaluate`
valide une intention et que l'opérateur écrive des règles fiables, le catalogue
est **figé et vérifié au démarrage** (schéma par capacité) — pas rechargé à chaud.
Un agent qui changerait ses capacités en cours de route déplacerait le sol sous la
politique ; c'est interdit.

## Frontière de tokenisation

```
tokenize(text | struct, vault) -> (tokenisé, vault)
detokenize(struct, vault) -> struct
```

- L'extracteur NER repère les entités sensibles (IP, HOSTNAME, VPN_USER,
  SNMP_COMMUNITY, HASH, MAC…) et les remplace par des jetons stables (`IP_1`,
  `VPN_USER_2`). Le `vault` (jeton→valeur réelle) est **lié à la session** et n'est
  **jamais sérialisé hors du serveur**.
- `detokenize` n'est appelée qu'au **seul** endroit légitime : dans `execution/`,
  juste avant l'appel `clients/` vers l'équipement.

### Invariants

- Tout ce qui entre dans le LLM et tout ce qui part dans `audit/` est
  **tokenisé** (test de propriété : aucune valeur du `vault` dans le prompt ni dans
  une ligne de log).
- Le `vault` ne franchit **jamais** la frontière serveur (ni LLM, ni logs, ni
  réponse HTTP).
- Bijection **par session** : `IP_1` désigne la même IP tout au long d'un plan ;
  deux sessions n'ont aucun jeton en commun.

### Règles vs jetons (décision YAGNI)

`evaluate` travaille sur des **jetons**. Une règle ne peut donc pas dire « deny si
IP ∈ 10.0.0.0/8 ». **Décision** : les règles ne portent que sur des attributs
**non sensibles** (capacité, interface, port, type) — suffisant pour l'écrasante
majorité des politiques, et le LLM reste aveugle aux valeurs. On n'enrichit le
jeton de métadonnées non réversibles (`IP_1{scope: private}`) **que si** un besoin
de politique réel le prouve.

## Auth & point de passage obligé

Deux gardes **distincts** (l'audit les avait vus fusionnés et troués) :

- **Auth** (*qui* appelle) : à la frontière HTTP, sur **toute** route, via une
  **dépendance FastAPI unique appliquée globalement** (on ne peut pas *oublier* de
  protéger une route neuve : le défaut est protégé, l'exemption est explicite).
  Clé(s) API par en-tête, comparées en **temps constant**, chargées depuis la
  config secrète (jamais en dur, jamais dans un artefact de build).
  **Fail-closed au démarrage** : le serveur **refuse de booter** sans secret d'auth
  configuré. Pas de « mode dev » silencieux par défaut ; l'opt-out local est
  bruyant et jamais l'état livré.
- **Politique** (*quelle action*) : au niveau de l'intention (ci-dessus).
  Orthogonal — être authentifié ≠ pouvoir tout faire.

### Infranchissabilité par les types

`execution/` n'expose **aucune** fonction prenant une `Intention` brute. Seule
porte :

```
execute(authorization: Authorized, vault) -> Result
```

où `Authorized` est un type que **seul** le moteur de politique produit (verdict
`allow`, ou `approve` résolu). Court-circuiter la politique exigerait de fabriquer
un `Authorized` — impossible sans passer par `evaluate`. mypy strict devient un
gardien de sécurité.

## Checkpoint humain (résolution de `approve`)

Quand `evaluate` renvoie `approve`, le plan **se suspend** et une approbation en
attente est persistée. Le flux *race-safe* existant est conservé et durci.

Propriétés non négociables :

- **Défaut deny ici aussi** : une approbation jamais répondue (timeout, absence)
  → l'action **ne s'exécute pas**. L'inaction ne vaut jamais consentement.
- **Liaison exacte intention↔autorisation** : approuver produit un `Authorized`
  lié au **hash de l'intention précise** montrée. Intention différente d'un octet
  → `Authorized` ne matche plus. (Contre le bug de substitution de directive de
  l'audit.)
- **Un `approve` humain ne contourne pas la politique** : un `deny` reste `deny` ;
  aucun humain ne peut approuver ce que la politique interdit.

### Ce que voit l'humain qui approuve

L'opérateur humain est **à l'intérieur** de la frontière de confiance (il autorise
une action sur sa propre infra). La vue d'approbation lui présente donc les
**valeurs réelles** (détokenisées) — nécessaire pour décider en connaissance de
cause — à condition que :

- la vue soit servie sur le canal **authentifié**, rendue côté serveur, et
  **jamais persistée en clair** dans l'audit ;
- l'`audit/` ne garde que la version **tokenisée** + la décision (qui, quand,
  quelle règle).

Le LLM et les logs restent aveugles ; seul l'humain autorisé, au moment de
décider, voit le réel.

## Stratégie de test (écrite avant le code)

**Cœur pur (unitaire exhaustif, aucun mock d'infra) :**

- `evaluate` : table `(intention, policy) → effect` couvrant allow/approve/deny,
  l'**ordre de priorité**, le **défaut-deny**, et le rejet d'une politique invalide
  au démarrage.
- `tokenize`/`detokenize` : **test de propriété** — aucune valeur du `vault` dans
  la sortie tokenisée ; `detokenize(tokenize(x)) == x` ; deux sessions sans jeton
  commun.

**Invariants de sécurité (tests rouges si violés) :**

- introspection du routeur : **aucune** route sans dépendance d'auth ;
- le serveur **refuse de booter** sans secret d'auth ;
- `execution.execute` **n'accepte pas** une intention non autorisée (typage +
  test négatif) ;
- liaison intention↔`Authorized` : approuver X puis présenter X′ ≠ X → refus ;
- aucune valeur réelle du `vault` dans une ligne d'`audit`.

**Intégration (mockée, sans lab) :** flux complet
requête→tokenize→LLM(stub)→evaluate→(approve→humain)→execute→audit, avec LLM et
`clients/` mockés — on vérifie le **câblage** et les codes de sortie, pas
l'inférence.

## Hors périmètre (sous-projets suivants)

- **Multi-tenant / isolation** (cloisonnement politiques et vaults par tenant) →
  sous-projet **D**. A est conçu **mono-tenant mais sans état global partagé**
  (tout passe par un contexte explicite), pour ne pas bloquer D.
- **CAP v2** (schéma, transport durci) → sous-projet **B**.
- **Portabilité modèles/GPU** → sous-projet **C**.
- **Licence, packaging, ops** → sous-projet **D**.

## Décisions actées (ne pas rouvrir)

| Sujet | Décision |
|---|---|
| Finalité | Produit déployable par des tiers |
| Contrôle | IA propose, politique + humain disposent ; LLM jamais final ; fail-closed |
| Forme politique | Déclarative en données → fonction **pure** → verdict, défaut **deny** |
| Données sensibles | **Tokenisation réversible** à la frontière ; LLM & logs voient des jetons ; détokenisation au seul point d'exécution (et vue d'approbation humaine) |
| Auth | Fail-closed au démarrage ; dépendance globale ; clé API temps constant |
| Infranchissabilité | Par les types (`Authorized` produit uniquement par la politique) |
| Catalogue capacités | Figé et vérifié au démarrage, pas rechargé à chaud |
| Multi-tenant | Repoussé à D ; A mono-tenant sans état global |
| Qualité | CQI > 9 dès le départ, test-first, mesuré par `cli-audit-code` |
