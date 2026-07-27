# Design — Enrichissement des jetons par `scope` (contexte de décision sans PII)

Date : 2026-07-27
Sujet : `cyber-agent-engine` — cœur de confiance (`core/tokens`, `core/policy`, `coordinator`)
Statut : conception détaillée — se poursuit en plan → build

## Contexte et objectif

La tokenisation PII remplace chaque valeur sensible par un jeton (`IP_ADDRESS_1`) avant
que le LLM ou la politique ne la voient. Le jeton préserve le **type** et l'**ordinal**,
mais **efface tout contexte de décision** : ni le proposer LLM ni le moteur de politique
ne peuvent savoir si `IP_ADDRESS_1` est publique, privée (RFC1918), loopback… Résultat :
aujourd'hui, **aucune décision automatique n'est possible sur la nature de l'adresse**
(p. ex. « refuser de bloquer une IP privée / de management ») — seul l'humain au gate,
ou l'équipement à l'exécution, voit la valeur réelle.

Objectif : **attacher au jeton une classification non-sensible (`scope`)**, calculée
côté serveur, et l'exposer **au proposer LLM (légende)** et **au moteur de politique
(pseudo-args synthétiques)** — **sans jamais révéler l'adresse**. Le zéro-secret est
préservé : seule la classe circule, la valeur reste dans le vault jusqu'à la frontière
d'exécution.

## Décisions actées (brainstorming)

- **`scope` d'abord, `zone` plus tard.** `scope` (public/private/loopback/…) est une
  propriété de l'adresse, calculable localement (`ipaddress` stdlib). La `zone`
  (WAN/DMZ/LAN/mgmt) exige la topologie de l'équipement → **incrément ultérieur**
  (carte opérateur `subnet→zone` ou capacité `classify_ip` de l'agent).
- **Pseudo-args synthétiques** côté politique : les règles matchent `ip__scope` via les
  ops existantes (`eq/in/…`). Le moteur `evaluate` **ne change pas** ; l'augmentation se
  fait dans `decide`, et l'`Intention` auditée/exécutée reste l'originale (jetons seuls,
  **aucune** clé synthétique).
- **Légende au LLM** : le prompt du proposer reçoit un contexte token→scope → le LLM
  raisonne sur la nature de l'IP sans la voir. Reste **non-décisionnel** (la politique
  tranche, fail-closed).

## Contrainte gouvernante — zéro-secret & fail-closed

- La valeur réelle ne quitte **jamais** le vault avant `core/execution/boundary.py`.
- `scope` est une **dérivation non-sensible** (classe d'appartenance), pas la valeur.
- La légende LLM et les pseudo-args ne contiennent **que** `<jeton> → <scope>`, jamais
  l'adresse.
- Rétrocompatibilité totale : `arg_meta` optionnel ; règles existantes inchangées ;
  légende vide ⇒ prompt identique à aujourd'hui. Fail-closed (défaut `deny`) inchangé.
- Aucune dépendance nouvelle (`ipaddress` est stdlib). Déterministe, testable en pur.

## Architecture

```
tokenize (Vault.token_for)                     ← calcule scope depuis la valeur réelle
    │  meta[token] = {"scope": "public|private|loopback|link_local|reserved"}
    ├─────────────▶ proposer.propose(request_tokens, history, context=<légende>)
    │                    (le LLM voit : IP_ADDRESS_1 = IPv4 publique)
    └─────────────▶ decide(intention, …, arg_meta={ "ip": {"scope": "private"} })
                         evaluate(augmented)   ← match ip__scope == private
                         Verdict.intention = ORIGINALE (jetons seuls)
```

### Composants (fichiers)

- **`core/tokens/vault.py`** (étendu) :
  - `classify_ip(value: str) -> str | None` — fonction pure stdlib `ipaddress` :
    `public` (global), `private` (RFC1918/ULA), `loopback`, `link_local`, `reserved` ;
    `None` si la valeur n'est pas une IP/subnet parsable.
  - `Vault.token_for(label, value)` : si `label ∈ {IP_ADDRESS, IP_SUBNET}`, calcule et
    stocke `self._meta[token] = {"scope": classify_ip(value)}` (si non-None).
  - `Vault.meta(token) -> dict[str,str]` + `Vault.meta_items() -> dict[str,dict]`.
  - `snapshot()`/`restore()` incluent `_meta` (persistance de session inchangée en forme).
- **`coordinator/loop.py`** (étendu) :
  - `_legend(vault) -> str` : construit la légende lisible depuis `vault.meta_items()`
    (`IP_ADDRESS_1 = IPv4 public`, une ligne/jeton porteur de meta) ; vide si aucun meta.
  - `_arg_meta(intention, vault) -> dict[str,dict]` : pour chaque `arg → jeton`, si le
    jeton a un meta, `{arg: {"scope": …}}`. Passé à `decide`.
  - `propose(request_tokens, history, context=_legend(vault))`.
- **`coordinator/proposer.py`** (étendu) :
  - `ProposerLike.propose(request_tokens, history, *, context: str = "")` (protocole).
  - `LlmProposer.propose` : si `context`, insère un message système additionnel
    « Contexte des jetons (non sensible) : … » **avant** l'observation. Le `_SYSTEM`
    rappelle que ce contexte est indicatif, jamais une valeur réelle à recopier.
- **`core/decision.py`** (étendu) :
  - `decide(intention, *, catalog, policy, sink, arg_meta=None, event=…)` : construit une
    **intention augmentée** (`args ∪ {f"{arg}__{k}": v}` depuis `arg_meta`) pour
    `evaluate` **uniquement** ; audite et renvoie un `Verdict` portant l'**intention
    originale**. `core/policy/engine.py` **inchangé**.
  - `core/orchestrator.py` (mono-action) : même signature `arg_meta` optionnelle (DRY).

### Format des pseudo-args (règles opérateur)

```yaml
# Refuser toute action qui bloquerait une IP privée (fail-closed avant même le gate).
- match: { capability: "opnsense.block_*", args: { ip__scope: { op: eq, value: private } } }
  effect: deny
  reason: "blocage d'une IP privée/interne refusé automatiquement"
```

Le séparateur `__` distingue un pseudo-arg (`<arg>__<clé_meta>`) d'un vrai arg. Les vrais
args gardent leur sémantique (jeton). Les pseudo-args n'existent **que** pendant le match.

## Mécanique

1. **Tokenisation** : `token_for` calcule `scope` pour les IP/subnets. `classify_ip` :
   parse via `ipaddress.ip_address`/`ip_network` (IP nue ou CIDR) ; renvoie la classe la
   plus précise ; `None` sur échec de parse (jamais d'exception propagée).
2. **Proposer** : la boucle passe la légende ; le LLM peut éviter de proposer une action
   absurde, mais ne s'auto-autorise pas (le champ reste hors `rationale`, non décisionnel).
3. **Décision** : `decide` augmente les args pour `evaluate`. Une règle `deny ip__scope ==
   private` déclenche un `deny` fail-closed **avant le gate**. Le `Verdict` audité porte
   l'intention **originale** (jetons), donc l'audit et l'exécution ne voient jamais de clé
   synthétique.
4. **Exécution** : inchangée (`boundary.py` détokenise la valeur réelle au dernier moment).

## Tests

**`core/tokens` (purs)** :
- `classify_ip` : `8.8.8.8`→public, `10.1.2.3`/`192.168.1.1`/`172.16.0.1`→private,
  `127.0.0.1`→loopback, `169.254.1.1`→link_local, `fd00::1`→private (ULA),
  `2620:fe::9`→public, `10.0.0.0/8`→private (subnet), `"pas-une-ip"`→None.
- `token_for` stocke le meta pour IP_ADDRESS/IP_SUBNET, pas pour HOSTNAME/CVE/…
- `snapshot`/`restore` : le meta survit au round-trip (session suspendue → reprise).
- **Zéro-secret** : `meta_items()` ne contient jamais la valeur brute ; la légende ne
  contient jamais l'adresse (assertion sur un sentinel = l'IP réelle).

**`core/policy` / `core/decision`** :
- `decide` avec `arg_meta={ip:{scope:private}}` + règle `deny ip__scope==private` → `deny`.
- La même intention sans la règle → comportement inchangé (rétrocompat).
- Le `Verdict.intention` **ne contient pas** `ip__scope` (clé synthétique non fuitée) ;
  l'entrée d'audit non plus.
- `engine.evaluate` reste couvert tel quel (aucune régression).

**`coordinator`** :
- `_legend`/`_arg_meta` dérivent correctement depuis un vault peuplé ; vides si aucun meta.
- `LlmProposer.propose(context=…)` insère bien le message de contexte (LLM mocké) ; sans
  `context`, messages identiques à aujourd'hui.
- Intégration boucle : requête « bloque 10.0.0.5 » + politique `deny ip__scope==private`
  → `deny` sans atteindre le gate ; « bloque 8.8.8.8 » → `approve` (gate) comme avant.

## Dépôt / structure

Tout dans le dépôt produit **`cyber-agent-engine`** (GitHub, branche
`feat/token-scope-enrichment` depuis `main`). AGPL/SPDX en tête des nouveaux fichiers.
Commits Conventional Commits en français, sans mention IA. Pas de secret, pas de
dépendance nouvelle.

## Risques / points d'attention

- **Le LLM sur-interprète la légende** : elle est indicative ; la politique reste la seule
  décisionnaire (fail-closed). Le prompt le rappelle explicitement.
- **Fuite de clé synthétique** : garantie évitée par la séparation dans `decide` (intention
  originale auditée/exécutée) — couverte par un test dédié.
- **IPv6 ULA vs global** : `ipaddress.is_private` couvre `fc00::/7` ; vérifié en test.
- **Meta périmé après re-tokenisation** : la re-tokenisation réutilise le vault existant
  (mêmes jetons) → le meta reste valide (pas de recalcul divergent).

## Hors périmètre (→ incréments ultérieurs)

- **`zone` (WAN/DMZ/LAN/mgmt)** : nécessite une source de topologie (carte opérateur
  `subnet→zone` chargée en config, ou capacité `classify_ip` de l'agent OPNsense).
- Métadonnées pour d'autres entités (hostname → interne/externe, port → bien-connu…).
- Exposition du `scope` dans la vue d'approbation humaine / le miroir SSE de la démo.
