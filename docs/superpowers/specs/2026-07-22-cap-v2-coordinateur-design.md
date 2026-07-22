# Design — Contrat CAP v2 & bascule du coordinateur (sous-projet B)

Date : 2026-07-22
Dépôt : `cyber-agent-engine` (public)
Statut : validé pour implémentation

## Contexte et cadrage

`cyber-agent-engine` est un coordinateur multi-agents où un LLM propose des
actions et les délègue à des agents-outils qui pilotent de **vrais** équipements
(OPNsense, WireGuard, CrowdSec). Le sous-projet A a livré le **cœur de confiance**
(`core/`) : moteur de politique déterministe fail-closed, auth sans faille,
frontière d'exécution avec preuve d'autorisation infalsifiable, tokenisation
réversible des valeurs sensibles, audit sur jetons, garde d'approbation humaine.

A n'a **pas** recâblé le coordinateur legacy : les 4 Criticals de l'audit
(`docs/audit-2026-07.md`) vivent encore dans `coordinator/pilot.py` (boucle ReAct
*fail-open*), `coordinator/judge.py` (`CAPValidator` *fail-open*) et le CAP v1
(champ `entities` porteur des PII NER brutes). B ferme cette dette : il définit le
**contrat CAP v2** et bascule le coordinateur sur `core/`.

**Finalité (rappel A)** : produit déployable par des tiers — sécurité par défaut,
garde-fous que l'opérateur ne contrôle pas à l'exécution. Décomposition :

- **A — Cœur de confiance & sûreté** *(livré, CQI core 9.2/10)*.
- **B — Contrat CAP v2 & bascule du coordinateur** *(ce spec)*. Dépend de A.
- **C — Portabilité modèles & runtime** (découpler des LoRA fine-tunés et de
  l'hypothèse GPU).
- **D — Packaging, licence, exploitation, isolation/multi-tenant, ISM policy**.

**Périmètre de B** : le contrat CAP v2, la bascule complète du coordinateur, et
**un** agent de référence de bout en bout — **CrowdSec**. OPNsense et WireGuard
suivent en B2 (ils réutilisent le même contrat et le même patron d'agent).

Ce spec est un **redesign dans le code existant** : la couche `clients/`
(transport UDS durci, qualité référence à l'audit) et le LLM brut multi-backend
(`coordinator/llm/coordinator_llm.py`) sont **conservés** ; c'est la chaîne de
décision au-dessus qui est refondue.

## Contrainte gouvernante — CQI > 9 dès le départ

Règle opérateur durable : qualité de code visée **> 9/10, atteinte à la
conception, pas en rétrofit**. B est donc **conçu** pour l'atteindre et livré
**test-first** :

- DAG de modules sans cycle : `contracts/cap.py` est une feuille pure ; `core/`
  reste en dessous ; le coordinateur est un orchestrateur mince composant des
  feuilles injectées derrière des Protocols.
- Toute I/O (LLM, client agent, stores) injectée derrière une interface, testée
  avec des doubles déterministes — aucun réseau, aucune horloge implicite.
- Fail-closed par défaut à chaque frontière ; aucun chemin legacy laissé « au
  cas où ».

## Deux faits du terrain qui cadrent le design

Vérifiés par inspection du code avant conception :

1. **L'agent a déjà un dispatch structuré.** `base.py` expose
   `_call_function(FunctionCall(function, args))` qui appelle directement la
   fonction enregistrée dans `self._functions`, **sans** passer par le SLM
   embarqué (`_infer_with_ollama`, chemin séparé). Migrer un agent sur CAP v2 est
   donc chirurgical : exposer un endpoint structuré qui valide un `CapPacket` et
   appelle `_call_function` — pas une réécriture de la logique métier.

2. **Le coordinateur n'a aucune sortie structurée.** Le README la promettait
   (vLLM `StructuredOutputsParams`) mais le code ne l'implémente pas (aucun
   Outlines/xgrammar/guided decoding). Le Proposer doit donc **parser + valider**
   le JSON du LLM en `core.Intention` avec retry borné — approche indépendante du
   backend, cohérente avec la portabilité visée en C. Le décodage contraint reste
   une amélioration future, non un prérequis.

## Architecture — chaîne de confiance de bout en bout

```
Requête HTTP  (auth globale : core.auth.make_auth_dependency, 401 fail-closed)
  → tokenize (core.tokens)                     ← le LLM ne voit que des jetons
  → BOUCLE ReAct gatée (coordinator/loop.py) :
      à chaque pas (borné) :
        Proposer (coordinator/proposer.py) : LLM → JSON → core.Intention validée
        → catalog.validate_intention → core.evaluate(intention, policy)
              deny    → core.audit → STOP (Denied)
              approve → ApprovalStore.create(hash canonique) + persister session
                        → STOP (Suspended)
              allow   → core.grant → execution.execute → CapPacket → agent → CapResult
                        → core.audit → résultat re-tokenisé → pas suivant
  (audit sur jetons uniquement, à chaque verdict)

  resume(approval_id) : recharge session → grant_approved → execute
                        → mark_executed (anti-rejeu) → continue la boucle
```

Frontière de responsabilités : la boucle **orchestre**, `core/` **décide et
exécute**, les agents **exécutent structurellement**. Le LLM ne fait que
**proposer**, jamais décider ni interpréter à l'exécution.

### Carte des modules

Nouveaux (package neutre + coordinateur refondu) :

- `contracts/cap.py` — **feuille pure**, sans dépendance. Contrat CAP v2 partagé
  coordinateur↔agents. Les agents ne dépendent pas du coordinateur, ni l'inverse.
- `coordinator/catalog_builder.py` — construit `core.CapabilityCatalog` depuis les
  **manifestes déclarés** des agents ; vérifie la conformance avec le
  `GET /capabilities` live au démarrage.
- `coordinator/proposer.py` — adapte le LLM brut en `core.Proposer` : prompt →
  JSON → `Intention` validée, retry borné sur sortie invalide.
- `coordinator/loop.py` — boucle ReAct gatée, multi-pas, avec suspend/resume.
- `coordinator/session.py` — `SessionStore` : état de session persisté (jetons,
  historique, index de pas, échéance), **chiffré au repos**.
- `coordinator/app.py` — app FastAPI recâblée : auth globale, routes déléguant à
  la boucle.

Réutilisés tels quels :

- `core/` (tout le sous-projet A).
- `coordinator/clients/tool_agent_client.py` (transport HTTP-over-UDS durci).
- `coordinator/llm/coordinator_llm.py` (LLM brut multi-backend).
- `agents/base.py` (`_call_function`, dispatch structuré) et
  `agents/crowdsec_agent.py` (les 5 fonctions métier).

Supprimés (remplacés, pas dépréciés) :

- `coordinator/pilot.py` (ReAct fail-open + chemin mort `plan()`).
- `coordinator/judge.py` (`CAPValidator` fail-open → remplacé par `core.policy`).
- Le champ `entities` et le CAP v1 dans `coordinator/models.py`.
- Les routes NL non gardées de l'ancienne app.

## Le contrat CAP v2

Modèle Pydantic partagé, validé aux **deux bouts** contre le même schéma :

```python
# contracts/cap.py
class CapPacket(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    function: str                     # nom NON qualifié, ex. "ban_ip"
    args: dict[str, str] = {}         # valeurs RÉELLES (détokenisées), bornées

class CapResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "error"]
    data: dict[str, Any] | None = None
    message: str | None = None
```

Décisions :

- **Plus de champ `entities`.** C'était le vecteur de fuite PII du CAP v1. En v2,
  les args réels arrivent déjà détokenisés par `execution.execute` ; l'agent n'a
  rien à réinterpréter.
- **Nom de fonction non qualifié.** Le catalogue namespace les capacités
  (`crowdsec.ban_ip`) pour la politique et le LLM ; l'adaptateur retire le
  namespace avant l'envoi à l'agent, qui ne connaît que ses propres fonctions.
- **Borné.** Taille de requête ET de réponse plafonnée (l'audit notait un
  `resp.json()` non borné) ; rejet avant désérialisation lourde.
- **Validé aux deux bouts.** Le coordinateur sérialise un `CapPacket` validé ;
  l'agent le re-valide (`extra="forbid"`) avant de vérifier que `function` est
  dans `_functions`, puis dispatche via `_call_function` — **sans SLM**. Un
  packet malformé est rejeté `CapResult(status="error")`, jamais exécuté.

Un test de conformité vérifie que coordinateur et agent valident le même schéma.

## Le Proposer et le catalogue

**Proposer** (`core.Proposer` adapté) :

- prompt = requête **tokenisée** + contexte du pas + schéma des fonctions du
  catalogue ;
- le LLM émet du JSON `{capability, args}` ; parse + validation (capacité ∈
  catalogue, args conformes) → `core.Intention` ;
- sur invalide (JSON cassé, capacité inconnue, arg manquant) : **retry borné**
  avec l'erreur renvoyée au LLM ; après N échecs, le pas échoue proprement ;
- les `args` restent des **jetons** (la requête est tokenisée) — invariant de A.

**Catalogue — déclaré + conformance** (et non découverte live pure) :

- chaque agent porte un **manifeste de capacités déclaré** (fichier versionné :
  fonctions, args requis, types). Le catalogue et la validation de politique se
  construisent depuis ces déclarations — **déterministe**, indépendant de la
  disponibilité des agents. Évite le couplage « un agent down empêche le
  démarrage » induit par le contrôle zéro-match de `load_policy`.
- au démarrage, le coordinateur interroge le `GET /capabilities` de chaque agent
  **joignable** et vérifie la **correspondance** avec sa déclaration. Écart (drift
  de capacités) → **erreur de démarrage fail-closed**. Agent injoignable →
  warning (ses actions échoueront proprement à l'exécution, pas une faille).

## La boucle ReAct gatée

`coordinator/loop.py` réécrit `pilot.py`. `handle()` retourne un résultat typé :
`Completed | Suspended(approval_id) | Denied | Failed`.

- **`approve` suspend TOUTE la boucle**, pas seulement le pas. On persiste l'état
  de session dans le `SessionStore`, on rend un `approval_id`, le processus
  s'arrête. Pas d'attente bloquante ni de thread suspendu — **reprise explicite**.
- **`resume(approval_id)`** : recharge la session, exécute le pas approuvé
  (`grant_approved` → `execution.execute`), `mark_executed` (anti-rejeu, corrigé
  en A), puis **continue** aux pas suivants. `reject` clôt la session (`Denied`).
- **Le LLM ne voit jamais la valeur réelle** : l'historique repassé au LLM est
  re-tokenisé (une IP dans un résultat d'agent ressort en `IP_2`).
- **Dette A adressée** : les approbations jamais résolues laissaient fuiter le
  vault (pas de TTL). La session persistée porte une **échéance** ; une session
  expirée purge ses jetons. Horloge **injectable** (pas de `Date.now()` en dur),
  pour rester testable.
- **Session chiffrée au repos** dans le `SessionStore` : elle contient le mapping
  jeton→valeur réelle (PII). Store fichier chiffré pour le MVP, interface
  abstraite pour brancher un KV plus tard.

## L'agent de référence CrowdSec

```
POST /agent/execute/cap  (sur la chaîne de confiance)
  body ← CapPacket (re-validé, borné)
  si body.function ∉ self._functions → CapResult(status="error")   # fail-closed
  résultat ← self._call_function(FunctionCall(body.function, body.args))
  → CapResult(status="ok", data=…)
```

- Les 5 fonctions existantes (`ban_ip`, `unban_ip`, `get_decisions`,
  `add_decision`, `delete_decision`) restent le point de dispatch, **inchangées
  dans leur logique** (elles pilotent le vrai `cscli`/LAPI).
- `_infer_with_ollama` est **retiré du chemin de confiance** : le SLM embarqué
  n'est plus appelé via `/execute/cap`. Retrait complet recommandé en B2.
- L'agent porte son **manifeste de capacités déclaré**, que `GET /capabilities`
  doit refléter (conformance au démarrage).
- Args **déjà détokenisés** : l'agent reçoit la vraie IP, l'utilise, et ne
  journalise **jamais** de PII brute (correction du Critical C2 ; logging aligné
  sur jetons/hashes).

## Fermeture des Criticals de l'audit

- **C1 `/api/command` sans auth** → `core.auth.make_auth_dependency` en dépendance
  **globale** dans `app.py` ; aucune route de la chaîne sans clé vérifiée
  (`hmac.compare_digest`, 401) ; refus de démarrer si le secret est absent
  (`AuthNotConfigured`).
- **C2 PII NER journalisée + exposée `/api/logs`** → champ `entities` supprimé,
  audit sur jetons, agent sans logging de PII, route `/api/logs` retirée.
- **C3 token publié** → gitignore déjà corrigé (619ff73) ; B ajoute le contrôle :
  aucun secret dans le bundle, clé d'auth issue de l'environnement/secret.
- **C4 auth fail-open + `/api/status`** → fail-closed global ; `/api/status` ne
  divulgue plus d'état interne sans auth.

**Règle tenue** : ce qui est remplacé est supprimé dans le même commit que son
remplaçant — jamais deux façons d'exécuter une action, une gardée et une non
gardée.

## Tests et qualité

Test-first, par couche, avec doubles déterministes (aucun réseau, aucune horloge
implicite) :

1. Contrat CAP v2 : round-trip, `extra="forbid"`, bornes — écrit avant `cap.py`.
2. Proposer : parse/valide/retry — **faux LLM** émettant du JSON scripté (dont
   invalide, pour couvrir le retry borné).
3. Boucle gatée : `Completed`/`Suspended`/`Denied`, cycle suspend→resume→continue,
   anti-rejeu, expiration de session (horloge injectée).
4. Catalogue + conformance : match, drift → erreur de démarrage (faux client).
5. Agent structuré : `/execute/cap` avec `CapPacket` valides et malformés
   (fail-closed) ; `_call_function` avec `cscli`/LAPI mockés.
6. **Intégration bout-en-bout** : requête → politique → (approbation) →
   `/execute/cap` → `cscli` mocké → audit, en vérifiant qu'**aucune PII**
   n'apparaît dans l'audit ni les logs (non-régression C2/C4).

Invariants vérifiés par les tests, pas seulement par revue :

- le LLM ne reçoit que des jetons (assertion sur les prompts capturés) ;
- aucune route non gardée (balayage de l'app exigeant la dépendance auth) ;
- fail-closed partout : secret absent → refus de démarrer ; capacité inconnue →
  deny ; packet malformé → error.

Chaque tâche passe par le cycle SDD (implémenteur + reviewer spec+qualité) ; revue
finale branche entière avant merge.

## Dette explicitement reportée

- **B2** : agents OPNsense et WireGuard sur CAP v2 ; retrait complet du SLM
  embarqué (`_infer_with_ollama`) et de la dépendance Ollama.
- **C** : portabilité modèles/runtime (le Proposer parse+valide déjà indépendant
  du backend ; le décodage contraint est une amélioration C).
- **D** : `SessionStore` sur KV réel, ISM policy, multi-tenant, licence.
- De A : `matched_rule.reason` perdu dans l'audit post-approbation — à propager
  ici si trivial, sinon D.

## Hors périmètre

- Toute amélioration du LLM lui-même (fine-tuning, LoRA) — relève de C.
- OPNsense/WireGuard end-to-end — B2.
- Packaging/distribution/licence — D.
