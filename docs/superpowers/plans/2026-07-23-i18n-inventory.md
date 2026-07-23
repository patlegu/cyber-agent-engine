# Inventaire des cibles D3d — messages opérateur à traduire en anglais

**Total cibles : 229**

> Généré par AST. Cibles = littéraux accentués dans args+kwargs de `raise` / `logging.*` / `print`, plus les champs de réponse opérateur `reason=` (loop) et `error=` (server). Docstrings, commentaires, prompts LLM, descriptions d'outils, vocab classifier, regex ReAct = HORS périmètre (restent FR).

## T1 — core/ + coordinator/ + server.py — 8 fichiers, 17 cibles

### `coordinator/app.py`
- L48 `raise` — `variante LoopResult non sérialisée : `

### `coordinator/assembly.py`
- L66 `raise` — `' exposé par plusieurs serveurs (routage ambigu)`
- L71 `raise` — `aucun agent découvert sur les serveurs d'agents`

### `coordinator/loop.py`
- L102 `reason=` — `session inconnue ou expirée`
- L114 `reason=` — `approbation en état `
- L142 `reason=` — `rejeté par l'opérateur`

### `coordinator/session.py`
- L102 `raise` — ` absent : le coordinateur refuse de démarrer`

### `core/auth/api_key.py`
- L26 `raise` — ` absent ou vide : le coordinateur refuse de démarrer sans authentification`
- L43 `raise` — `clé API invalide ou absente`

### `core/execution/authorization.py`
- L29 `raise` — `Authorized ne peut être construit que par grant()/grant_approved()`
- L46 `raise` — ` en état `

### `core/policy/loading.py`
- L31 `raise` — ` malformée : `
- L31 `raise` — `règle #`
- L34 `raise` — `' ne couvre aucune capacité connue`
- L34 `raise` — `règle #`

### `server.py`
- L138 `log` — `  ⚠️  Adapter '%s' ignoré — base model incompatible (adapter: %s, attendu: %s). Re-entraîn`
- L342 `error=` — `Aucun agent n'a pu interpréter cette commande.`

## T2 — clients/ — 3 fichiers, 18 cibles

### `clients/opnsense_api_client.py`
- L70 `log` — `OPNsense API Client initialisé: `
- L650 `log` — `Erreur téléchargement backup: `

### `clients/pfsense_api_client.py`
- L55 `log` — `Client API pfSense initialisé (version: `
- L114 `log` — `Erreur requête `
- L259 `log` — `Erreur récupération version: `

### `clients/wireguard_linux_client.py`
- L35 `log` — `Client WireGuard Linux initialisé (config: `
- L41 `log` — `Exécution: `
- L56 `raise` — `Commande échouée (`
- L91 `log` — `Paire de clés WireGuard générée`
- L106 `log` — `PSK WireGuard générée`
- L156 `log` — ` créée (`
- L170 `log` — ` démarrée`
- L173 `log` — `Erreur démarrage `
- L180 `log` — ` arrêtée`
- L183 `log` — `Erreur arrêt `
- L198 `log` — ` supprimée`
- L235 `log` — `Peer ajouté à `
- L242 `log` — `... supprimé de `

## T3 — agents/ (hors opnsense) — 12 fichiers, 74 cibles

### `agents/__init__.py`
- L85 `raise` — `. Types supportés: `

### `agents/anony/agent.py`
- L119 `log` — `AnonyNER introuvable (package '%s' ni répertoire '%s') — fallback en_core_web_md. Installe`
- L126 `log` — `AnonyNER résolu : %s`
- L187 `log` — `custom_rules chargées depuis %s (%d règles)`
- L190 `log` — `custom_rules_security.json introuvable (%s) — désactivées`
- L203 `raise` — `anonyfiles_core non installé.\n  Dev  : pip install -e /srv/anonyfiles\n  Prod : pip insta`
- L214 `log` — `AnonyfilesEngine initialisé (spaCy: %s, labels_cyber: %d, custom_rules: %s)`
- L235 `log` — `NERExtractor initialisé (modèle : %s)`
- L237 `log` — `NERExtractor désactivé — AnonyNER introuvable`
- L239 `log` — `NERExtractor non importable — désactivé`
- L295 `log` — `NER gap : '%s' (%s) détecté mais non anonymisé par le moteur`
- L355 `log` — `NER gap batch : '%s' (%s) non anonymisé par le moteur`
- L423 `log` — `Entrées corrompues filtrées du mapping (bug engine : NER sur texte post-custom_rules) : %s`

### `agents/base.py`
- L132 `log` — ` initialisé avec `
- L382 `log` — `Erreur lors de l'exécution: `
- L458 `log` — `Mode Ollama activé (modèle: `
- L465 `log` — `ℹ️ Agent initialisé en mode 'Tools-Only' (pas de modèle LoRA local)`
- L467 `log` — `⚠️ Modèle LoRA non trouvé au chemin spécifié: `
- L471 `log` — `✅ Inférence déportée active via Ollama`
- L473 `log` — `ℹ️ Inférence locale désactivée (mode simulation pour les requêtes NL)`
- L480 `log` — `Chargement du modèle LoRA depuis `
- L493 `log` — `✓ Modèle LoRA chargé avec succès`
- L496 `log` — `ℹ️ Unsloth n'est pas installé (utilisé pour l'inférence LoRA locale)`
- L498 `log` — `❌ Erreur lors du chargement du modèle LoRA: `
- L499 `log` — `❌ Erreur lors du chargement du modèle LoRA: `
- L500 `log` — `ℹ️ Fallback sur le mode simulation pour l'inférence`
- L555 `log` — `Erreur inférence vLLM: `
- L597 `raise` — `Aucun backend d'inférence configuré (AGENT_INFER_BASE_URL/ollama/[gpu]). Le chemin structu`
- L647 `log` — `LoRA inférence: `
- L652 `log` — `Erreur lors de l'inférence LoRA: `
- L678 `log` — `Réponse Ollama: `
- L683 `log` — `Erreur inférence Ollama: `
- L879 `log` — `Modèle a retourné une liste vide, interprété comme 'unknown'.`
- L917 `log` — `Fonction identifiée: `
- L1007 `log` — `Aucune fonction valide identifiée dans la réponse du modèle`

### `agents/coercion.py`
- L55 `raise` — ` n'est pas un booléen`

### `agents/crowdsec_agent.py`
- L177 `log` — `Réponse Ollama: `
- L182 `log` — `Erreur inférence Ollama: `
- L222 `log` — ` (durée: `
- L246 `log` — `[CrowdSec] Débannissement IP: `
- L283 `log` — `[CrowdSec] Consultation décisions (limit: `
- L331 `log` — `[CrowdSec] Ajout décision: `
- L352 `log` — `[CrowdSec] Suppression décision: `
- L479 `log` — `[CrowdSec] Vérification allowlist: `
- L582 `log` — ` (scénario: `

### `agents/manifest.py`
- L65 `raise` — `: required déclaré `

### `agents/ner_extractor.py`
- L60 `log` — `AnonyNER chargé depuis %s`
- L63 `log` — `spaCy non disponible — NERExtractor désactivé`
- L67 `log` — `Modèle AnonyNER introuvable : %s — NERExtractor désactivé`

### `agents/pfsense_agent.py`
- L70 `log` — `✓ Client API pfSense initialisé`
- L106 `log` — `[pfSense] Création règle: `
- L130 `log` — `[pfSense] Création alias: `
- L145 `log` — `[pfSense] Consultation informations système`
- L151 `log` — `Erreur consultation système: `
- L191 `log` — ` installé`
- L219 `log` — ` fonctions enregistrées (40 OPNsense + 3 pfSense)`

### `agents/router_agent.py`
- L64 `log` — `Intention identifiée: `

### `agents/stormshield_agent.py`
- L65 `log` — `[Stormshield] Déblocage IP: `
- L83 `log` — `[Stormshield] Création règle: `
- L95 `log` — `[Stormshield] Suppression règle: `
- L123 `log` — `[Stormshield] Création objet réseau: `

### `agents/tool_agents.py`
- L35 `log` — `tool_agents.py est déprécié. Utilisez 'from agents import OPNsenseAgent' à la place. Voir `

### `agents/wireguard_agent.py`
- L152 `raise` — `Plateforme non supportée: `
- L154 `log` — `Agent WireGuard initialisé (platform: `
- L208 `log` — `Création tunnel Site-to-Site: `
- L242 `log` — `✓ Tunnel Site-to-Site créé: `
- L408 `log` — `Création tunnel Point-to-Point: `
- L470 `raise` — `Point-to-Point non encore implémenté pour OPNsense`
- L502 `log` — ` nœuds`
- L502 `log` — `Création réseau mesh avec `
- L570 `log` — ` nœuds`
- L570 `log` — `✓ Réseau mesh créé avec `
- L603 `log` — `Vérification du routage...`
- L616 `log` — `Rotation des clés pour `

## T4 — agents/opnsense/* — 11 fichiers, 120 cibles

### `agents/opnsense/_aliases.py`
- L19 `log` — `[OPNsense] Création alias: `
- L35 `log` — `' créé et appliqué`
- L38 `log` — `Erreur création alias: `
- L53 `log` — ` supprimé`
- L74 `log` — ` modifié`
- L105 `log` — ` effectué`
- L123 `log` — ` vidé`
- L134 `log` — ` à alias `
- L140 `log` — ` ajouté à `
- L143 `log` — `Erreur ajout à alias: `
- L157 `log` — ` retiré de `
- L180 `log` — `[OPNsense] Recherche références alias: `
- L186 `log` — `Erreur recherche références: `

### `agents/opnsense/_base.py`
- L163 `log` — `✓ Client API OPNsense initialisé`
- L165 `log` — `OPNsense: Initialisé sans API (mode locale/simulation)`
- L175 `log` — `✓ Client API pfSense initialisé (Polyfill)`
- L177 `log` — `pfSense: Initialisé sans API (mode locale/simulation)`
- L182 `log` — `✓ Client Système Linux initialisé (Polyfill)`

### `agents/opnsense/_config.py`
- L22 `log` — `✓ Changements appliqués avec succès`
- L37 `log` — `✓ Rollback annulé, changements confirmés`
- L52 `log` — `✓ Changements annulés`
- L62 `log` — `[OPNsense] Création savepoint`
- L67 `log` — `✓ Savepoint créé: `
- L70 `log` — `Erreur création savepoint: `
- L92 `log` — `[OPNsense] Téléchargement backup configuration`
- L148 `log` — `). Le système peut redémarrer.`
- L148 `log` — `⚠ Restauration déclenchée (`
- L158 `log` — `[OPNsense] Création point de sauvegarde: `
- L164 `log` — `Erreur création savepoint: `

### `agents/opnsense/_diagnostics.py`
- L16 `log` — `[Polyfill] Récuperation status (platform=`
- L54 `log` — `[OPNsense] Consultation états`
- L60 `log` — `Erreur consultation états: `
- L67 `log` — `[OPNsense] Kill états: `
- L72 `log` — `✓ États terminés: `
- L75 `log` — `Erreur kill états: `
- L82 `log` — `[OPNsense] Flush tous les états`
- L87 `log` — `✓ Tous les états terminés: `
- L90 `log` — `Erreur flush états: `
- L110 `log` — `[OPNsense] Consultation stats règles`
- L116 `log` — `Erreur consultation stats règles: `

### `agents/opnsense/_extended.py`
- L21 `log` — `[OPNsense] Création catégorie: `
- L29 `log` — `' créée`
- L29 `log` — `✓ Catégorie '`
- L32 `log` — `Erreur création catégorie: `
- L40 `log` — `[OPNsense] Suppression catégorie: `
- L47 `log` — ` supprimée`
- L47 `log` — `✓ Catégorie `
- L50 `log` — `Erreur suppression catégorie: `
- L57 `log` — `[OPNsense] Liste catégories`
- L63 `log` — `Erreur liste catégories: `
- L71 `log` — `[OPNsense] Mise à jour bogons`
- L76 `log` — `✓ Bogons mis à jour`
- L79 `log` — `Erreur mise à jour bogons: `
- L116 `log` — `[OPNsense] Vérification mises à jour`
- L125 `log` — `Erreur vérification updates: `
- L155 `log` — `⚠ Upgrade lancé. Le système va peut-être redémarrer.`
- L229 `log` — `[OPNsense] Recherche requêtes DNS: '`
- L313 `log` — `[OPNsense] Mise à jour certificat ACME: `
- L318 `log` — `Erreur mise à jour certificat ACME: `
- L327 `log` — `[OPNsense] Révocation certificat ACME: `
- L332 `log` — `Erreur révocation certificat ACME: `

### `agents/opnsense/_filters.py`
- L84 `log` — `[OPNsense] Création règle: `
- L112 `log` — `' créée et appliquée`
- L112 `log` — `✓ Règle '`
- L117 `log` — `Erreur création règle: `
- L130 `log` — `[OPNsense] Suppression règle: `
- L137 `log` — ` supprimée et appliquée`
- L137 `log` — `✓ Règle `
- L140 `log` — `Erreur suppression règle: `
- L148 `log` — `[OPNsense] Modification règle: `
- L156 `log` — ` modifiée et appliquée`
- L156 `log` — `✓ Règle `
- L159 `log` — `Erreur modification règle: `
- L167 `log` — `[OPNsense] Toggle règle `
- L174 `log` — `activée`
- L174 `log` — `désactivée`
- L174 `log` — `✓ Règle `
- L177 `log` — `Erreur toggle règle: `
- L185 `log` — `[OPNsense] Déplacement règle `
- L192 `log` — ` déplacée`
- L192 `log` — `✓ Règle `
- L195 `log` — `Erreur déplacement règle: `
- L207 `log` — `[OPNsense] Consultation règles`
- L214 `log` — `Erreur consultation règles: `

### `agents/opnsense/_ids.py`
- L146 `log` — `[OPNsense] Mise à jour des règles IDS`
- L151 `log` — `Erreur mise à jour règles IDS: `
- L157 `log` — `[OPNsense] Démarrage IDS`
- L162 `log` — `Erreur démarrage IDS: `
- L168 `log` — `[OPNsense] Arrêt IDS`
- L173 `log` — `Erreur arrêt IDS: `
- L179 `log` — `[OPNsense] Redémarrage IDS`
- L184 `log` — `Erreur redémarrage IDS: `

### `agents/opnsense/_legacy.py`
- L35 `log` — `Alias BlockedIPs introuvable, création en cours...`
- L67 `log` — `[OPNsense] Déblocage IP: `
- L79 `log` — `Erreur déblocage IP: `

### `agents/opnsense/_nat.py`
- L19 `log` — `[OPNsense] Création NAT sortant: `
- L33 `log` — `✓ NAT sortant créé`
- L36 `log` — `Erreur création NAT sortant: `
- L51 `log` — ` supprimé`
- L87 `log` — `✓ Port forward créé`
- L90 `log` — `Erreur création port forward: `
- L113 `log` — `✓ NAT 1:1 créé`
- L116 `log` — `Erreur création NAT 1:1: `
- L131 `log` — ` supprimé`

### `agents/opnsense/_traffic.py`
- L60 `log` — `[OPNsense] Création pipe: `
- L70 `log` — `' créé`
- L73 `log` — `Erreur création pipe: `
- L121 `log` — `[OPNsense] Création queue: `
- L131 `log` — `' créée`
- L134 `log` — `Erreur création queue: `
- L160 `log` — `[OPNsense] Liste des règles traffic shaping`
- L165 `log` — `Erreur liste règles trafic: `
- L186 `log` — `[OPNsense] Création règle trafic: `
- L198 `log` — `' créée`
- L198 `log` — `✓ Règle trafic '`
- L201 `log` — `Erreur création règle trafic: `
- L211 `log` — `[OPNsense] Suppression règle trafic: `
- L218 `log` — `Erreur suppression règle trafic: `

### `agents/opnsense/_vpn.py`
- L103 `log` — `[OPNsense] Déconnexion session IPsec: `
- L108 `log` — `Erreur déconnexion session IPsec: `
