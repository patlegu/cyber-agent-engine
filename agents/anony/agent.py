"""
agents/anony/agent.py

Agent d'anonymisation qui orchestre anonyfiles_core comme moteur.

Architecture :
  NERExtractor  (agents/ner_extractor.py) = détection NER sécurité (AnonyNER spaCy)
  AnonyfilesEngine (anonyfiles_core)       = muscle — regex, remplacement, réversibilité
  AnonyAgent (cyber-agent-engine)          = cerveau — coordination, batch, session

Flux d'anonymisation (anonymize_text) :
  1. Moteur traite le texte : custom rules regex + NER AnonyNER intégré
     → cohérence intra-session via ReplacementGenerator stateful (même entité = même token)
  2. NER extrait les entités du texte original (observabilité — log des gaps moteur)
  3. Retour : {anonymized_text, mapping, entities_detected}

Cohérence garantie :
  - intra-texte  : session stateful du ReplacementGenerator
  - cross-appels : idem (même instance de moteur, compteurs partagés)
  - cross-fichiers (batch) : idem — session unique sur tout le batch

Limite connue (anonyfiles_core) :
  Le moteur applique les custom rules AVANT le NER. Les tokens {{...}} produits par
  les règles regex s'intègrent dans le texte NER, ce qui peut dans certains contextes
  classer des spans adjacents comme de nouvelles entités (ex: {{IP_PRIVE}} — HOSTNAME).
  Fix requis côté moteur : exécuter le NER sur le texte original avant les custom rules.

NER dans ce pipeline :
  - Rôle : observabilité uniquement — détecter ce que le moteur a manqué
  - Pas de seeding/pre-substitution : le moteur est le seul générateur de tokens
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base import ToolAgent

# Nom du package spaCy installé (via pip install dist/en_anonyner-*.tar.gz).
# Priorité 1 : package installé (en_anonyner) — fichier unique, portable.
# Priorité 2 : répertoire model-best — présent en dev après train_anonyner.py.
# Priorité 3 : en_core_web_md — fallback sans entités cyber.
_ANONYNER_PACKAGE = "en_anonyner"
_ANONYNER_MODEL_PATH = Path(__file__).parent.parent.parent / "models" / "anonyner_model" / "model-best"


def _resolve_anonyner_model() -> str:
    """Retourne le nom/chemin du modèle AnonyNER disponible, par ordre de priorité."""
    import importlib.util
    if importlib.util.find_spec(_ANONYNER_PACKAGE) is not None:
        return _ANONYNER_PACKAGE
    if _ANONYNER_MODEL_PATH.exists():
        return str(_ANONYNER_MODEL_PATH)
    return None

logger = logging.getLogger(__name__)

# Chemin par défaut des règles de détection sécurité,
# colocalisé avec l'agent pour l'isolation du package.
_DEFAULT_RULES_PATH = Path(__file__).parent / "config" / "custom_rules_security.json"


class AnonyAgent(ToolAgent):
    """
    Orchestre l'anonymisation de logs et documents via anonyfiles_core.

    Fonctions exposées au coordinateur :
      - anonymize_text(text)              — anonymise un texte en mémoire
      - anonymize_batch(texts)            — batch cohérent multi-textes
      - deanonymize_text(anonymized_text) — réversibilité via le mapping de session
      - get_session_mapping()             — mapping courant {original: token}
      - reset_session()                   — repart d'une session vierge
    """

    def __init__(
        self,
        config: Optional[Dict] = None,
        custom_rules_path: Optional[str] = None,
        **kwargs,
    ):
        """
        :param config: Configuration passée à AnonyfilesEngine (labels, modèle spaCy…).
                       Voir _default_config() pour les valeurs par défaut.
        :param custom_rules_path: Chemin vers custom_rules_security.json.
                                  Si None, utilise agents/anony/config/custom_rules_security.json.
        """
        super().__init__(tool_name="anony", model_path=None, **kwargs)

        self.config = config or self._default_config()
        self._custom_rules: Optional[List[Dict]] = self._load_custom_rules(custom_rules_path)

        # Moteur lazy-init : le chargement spaCy est coûteux, on attend le premier appel
        self._engine = None

        # Mapping de session accumulé sur tous les appels — miroir de la session moteur.
        # Sert à deanonymize_text() et à l'export du mapping complet.
        # Format : {texte_original: token_anonyme}
        self._session_mapping: Dict[str, str] = {}

        # NERExtractor lazy — None jusqu'au premier appel, puis instance partagée
        self._ner = None
        self._ner_ready: bool = False

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _default_config(self) -> Dict:
        # Résolution du modèle par ordre de priorité :
        #   1. Package installé : en_anonyner  (pip install dist/en_anonyner-*.tar.gz)
        #   2. Répertoire local : models/anonyner_model/model-best  (après train_anonyner.py)
        #   3. Fallback         : en_core_web_md  (entités cyber non détectées)
        anonyner = _resolve_anonyner_model()
        spacy_model = anonyner or "en_core_web_md"
        if not anonyner:
            logger.warning(
                "AnonyNER introuvable (package '%s' ni répertoire '%s') — "
                "fallback en_core_web_md. "
                "Installer avec : pip install dist/en_anonyner-*.tar.gz",
                _ANONYNER_PACKAGE,
                _ANONYNER_MODEL_PATH,
            )
        else:
            logger.debug("AnonyNER résolu : %s", spacy_model)

        return {
            "spacy_model": spacy_model,
            # Entités NLP classiques (fr_core_news_md ou AnonyNER si labels hérités)
            "anonymizePersons": True,
            "anonymizeLocations": True,
            "anonymizeOrgs": True,
            "anonymizeEmails": True,
            "anonymizeDates": True,
            "anonymizeMisc": False,
            "anonymizePhones": True,
            # Labels spécifiques AnonyNER — injectés via extra_labels (fork)
            # Activés uniquement si le modèle AnonyNER est présent.
            "extra_labels": [
                "IP_ADDRESS", "IP_SUBNET",
                "HOSTNAME", "DOMAIN",
                "CVE",
                "MAC_ADDRESS",
                "SERVICE_ACCOUNT",
                "FIREWALL_RULE",
                "INTERFACE",
                "PORT_NUMBER",
                "VPN_USER",
                "PROTOCOL",
                "SERVICE",
            ] if anonyner else [],
            # Tags anglais pour le contexte cyber.
            # Surcharge les defaults français du fork (NOM, LIEU, ENTREPRISE…)
            "replacements": {
                # Labels NLP classiques
                "PER":   {"type": "codes", "options": {"prefix": "PERSON"}},
                "LOC":   {"type": "codes", "options": {"prefix": "LOCATION"}},
                "ORG":   {"type": "codes", "options": {"prefix": "ORG"}},
                "EMAIL": {"type": "codes", "options": {"prefix": "EMAIL"}},
                "DATE":  {"type": "codes", "options": {"prefix": "DATE"}},
                "MISC":  {"type": "codes", "options": {"prefix": "MISC"}},
                "PHONE": {"type": "codes", "options": {"prefix": "PHONE"}},
                "IBAN":  {"type": "codes", "options": {"prefix": "IBAN"}},
                # Labels AnonyNER — tags cyber lisibles
                "IP_ADDRESS":     {"type": "codes", "options": {"prefix": "IP"}},
                "IP_SUBNET":      {"type": "codes", "options": {"prefix": "SUBNET"}},
                "HOSTNAME":       {"type": "codes", "options": {"prefix": "HOST"}},
                "DOMAIN":         {"type": "codes", "options": {"prefix": "DOMAIN"}},
                "CVE":            {"type": "codes", "options": {"prefix": "CVE"}},
                "MAC_ADDRESS":    {"type": "codes", "options": {"prefix": "MAC"}},
                "SERVICE_ACCOUNT":{"type": "codes", "options": {"prefix": "SVC_ACCOUNT"}},
                "FIREWALL_RULE":  {"type": "codes", "options": {"prefix": "FW_RULE"}},
                "INTERFACE":      {"type": "codes", "options": {"prefix": "IFACE"}},
                "PORT_NUMBER":    {"type": "codes", "options": {"prefix": "PORT"}},
                "VPN_USER":       {"type": "codes", "options": {"prefix": "VPN_USER"}},
                "PROTOCOL":       {"type": "codes", "options": {"prefix": "PROTO"}},
                "SERVICE":        {"type": "codes", "options": {"prefix": "SVC"}},
            },
        }

    def _load_custom_rules(self, path: Optional[str]) -> Optional[List[Dict]]:
        resolved = Path(path) if path else _DEFAULT_RULES_PATH
        try:
            with open(resolved, encoding="utf-8") as f:
                rules = json.load(f)
            logger.info("custom_rules chargées depuis %s (%d règles)", resolved, len(rules))
            return rules
        except FileNotFoundError:
            logger.debug("custom_rules_security.json introuvable (%s) — désactivées", resolved)
            return None
        except Exception as e:
            logger.warning("Erreur chargement custom_rules: %s", e)
            return None

    def _get_engine(self):
        """Lazy-init : crée le moteur AnonyfilesEngine au premier appel."""
        if self._engine is None:
            try:
                from anonyfiles_core.anonymizer.engine import AnonyfilesEngine
            except ImportError as exc:
                raise RuntimeError(
                    "anonyfiles_core non installé.\n"
                    "  Dev  : pip install -e /srv/anonyfiles\n"
                    "  Prod : pip install 'anonyfiles_core @ git+https://github.com/patlegu/anonyfiles.git@main'"
                ) from exc

            self._engine = AnonyfilesEngine(
                config=self.config,
                custom_replacement_rules=self._custom_rules,
            )
            extra = self.config.get("extra_labels", [])
            logger.info(
                "AnonyfilesEngine initialisé (spaCy: %s, labels_cyber: %d, custom_rules: %s)",
                self.config.get("spacy_model"),
                len(extra),
                "oui" if self._custom_rules else "non",
            )
        return self._engine

    def _get_ner(self):
        """
        Lazy-init du NERExtractor, partageant le chemin modèle avec l'engine.

        Retourne None si AnonyNER n'est pas disponible (graceful degradation).
        """
        if not self._ner_ready:
            try:
                from ..ner_extractor import NERExtractor
                anonyner = _resolve_anonyner_model()
                if anonyner:
                    # Path("en_anonyner") → spacy.load("en_anonyner") ✓
                    # Path("/srv/.../model-best") → spacy.load("/srv/...") ✓
                    self._ner = NERExtractor(model_path=Path(anonyner))
                    logger.debug("NERExtractor initialisé (modèle : %s)", anonyner)
                else:
                    logger.debug("NERExtractor désactivé — AnonyNER introuvable")
            except ImportError:
                logger.debug("NERExtractor non importable — désactivé")
            self._ner_ready = True
        return self._ner

    # ------------------------------------------------------------------
    # Enregistrement des fonctions (interface ToolAgent)
    # ------------------------------------------------------------------

    def _register_functions(self) -> Dict[str, callable]:
        return {
            "anonymize_text": self.anonymize_text,
            "anonymize_batch": self.anonymize_batch,
            "deanonymize_text": self.deanonymize_text,
            "get_session_mapping": self.get_session_mapping,
            "reset_session": self.reset_session,
        }

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    async def anonymize_text(self, text: str) -> Dict[str, Any]:
        """
        Anonymise un texte en mémoire.

        Flux :
          1. Moteur traite le texte (custom rules regex + NER AnonyNER intégré)
             — La session interne du ReplacementGenerator garantit la cohérence
               intra-session : même entité NER → même token sur tous les appels.
             — Les custom rules (RFC1918, CVE…) appliquent des remplacements statiques
               cohérents par construction (même regex → même token fixe).
          2. NER extrait les entités du texte original — observabilité uniquement
             (log des gaps : entités vues par NER mais non anonymisées par le moteur)

        Limite connue (anonyfiles_core) : le moteur applique les custom rules AVANT le NER.
        Les tokens {{IP_PRIVE}} produits par les règles regex s'intègrent dans le texte
        soumis au NER, qui peut dans certains contextes classer des spans adjacents comme
        de nouvelles entités. Fix requis côté moteur : exécuter le NER sur le texte original.

        :return: {anonymized_text, total_replacements, mapping, entities_detected}
        """
        engine = self._get_engine()
        ner = self._get_ner()

        # Moteur : custom rules + NER + génération de tokens
        anonymized, report = engine.anonymize_text(text)
        self._session_mapping.update(self._sanitize_mapping(report.get("mapping", {})))

        # NER sur le texte original — observabilité uniquement (ne modifie pas le résultat)
        ner_entities: Dict[str, List[str]] = {}
        if ner and ner.is_available():
            ner_entities = ner.extract(text)
            for label, vals in ner_entities.items():
                for val in vals:
                    if val and val not in self._session_mapping:
                        logger.debug(
                            "NER gap : '%s' (%s) détecté mais non anonymisé par le moteur",
                            val, label,
                        )

        return {
            "anonymized_text": anonymized,
            "total_replacements": report["total_replacements"],
            "mapping": dict(self._session_mapping),
            "entities_detected": ner_entities,
        }

    async def anonymize_batch(
        self,
        texts: List[str],
        reset_session: bool = False,
    ) -> Dict[str, Any]:
        """
        Anonymise un lot de textes avec cohérence garantie sur tout le batch.
        La même entité reçoit le même token grâce à la session interne du moteur
        (ReplacementGenerator stateful) et aux custom rules idempotentes.

        La résolution d'aliases cross-entités (srv-web01 ↔ 192.168.10.50) nécessite
        shared_mapping_proxy — non implémenté côté anonyfiles_core.

        Flux :
          Phase 1 — Anonymisation texte par texte (engine stateful)
          Phase 2 — NER sur les textes originaux — inventaire de gaps (observabilité)

        :param texts:         Liste de textes à anonymiser.
        :param reset_session: Si True, repart d'une session vierge avant le batch.
        :return: {results: [{anonymized_text, replacements}], session_mapping, total_texts, ner_gaps}
        """
        if reset_session:
            await self.reset_session()

        engine = self._get_engine()
        ner = self._get_ner()
        original_texts = list(texts)

        # Phase 1 : Anonymisation texte par texte
        results = []
        for text in original_texts:
            anonymized, report = engine.anonymize_text(text)
            self._session_mapping.update(self._sanitize_mapping(report.get("mapping", {})))
            results.append({
                "anonymized_text": anonymized,
                "replacements": report["total_replacements"],
            })

        # Phase 2 : NER sur les textes originaux — inventaire de gaps (observabilité)
        ner_gaps: Dict[str, List[str]] = {}
        if ner and ner.is_available():
            for text in original_texts:
                for label, vals in ner.extract(text).items():
                    for val in vals:
                        if val and val not in self._session_mapping:
                            lst = ner_gaps.setdefault(label, [])
                            if val not in lst:
                                lst.append(val)
                                logger.debug(
                                    "NER gap batch : '%s' (%s) non anonymisé par le moteur",
                                    val, label,
                                )

        return {
            "results": results,
            "session_mapping": dict(self._session_mapping),
            "total_texts": len(original_texts),
            "ner_gaps": ner_gaps,
        }

    async def deanonymize_text(self, anonymized_text: str) -> Dict[str, Any]:
        """
        Réintroduit les valeurs originales à partir du mapping de session courant.

        :param anonymized_text: Texte contenant des tokens (ex: {{NOM_001}}).
        :return: {original_text, replacements_made}
        """
        result = anonymized_text
        count = 0

        # Tri par longueur de token décroissante pour éviter les collisions
        # ex: {{NOM_010}} avant {{NOM_01}}
        for original, token in sorted(
            self._session_mapping.items(), key=lambda x: len(x[1]), reverse=True
        ):
            if token in result:
                result = result.replace(token, original)
                count += 1

        return {"original_text": result, "replacements_made": count}

    async def get_session_mapping(self) -> Dict[str, Any]:
        """Retourne le mapping courant {entité_originale: token}."""
        return {"mapping": dict(self._session_mapping)}

    async def reset_session(self) -> Dict[str, Any]:
        """Repart d'une session vierge (efface le mapping accumulé)."""
        self._session_mapping.clear()
        if self._engine is not None:
            self._engine.reset_state()
        return {"status": "ok", "message": "Session réinitialisée"}

    # ------------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------------

    def _sanitize_mapping(self, mapping: Dict[str, str]) -> Dict[str, str]:
        """
        Filtre les entrées corrompues produites par le bug engine (NER exécuté après
        les custom rules : les tokens {{...}} injectés par les règles regex introduisent
        des accolades que le NER peut incorporer dans un span adjacent).

        Une entrée est considérée corrompue si sa clé (texte original) contient
        '{' ou '}' — ces caractères n'apparaissent pas dans des logs bruts authentiques.

        :param mapping: mapping brut retourné par engine.anonymize_text()
        :return: mapping nettoyé
        """
        clean = {}
        corrupted = []
        for original, token in mapping.items():
            if '{' in original or '}' in original:
                corrupted.append(original)
            else:
                clean[original] = token
        if corrupted:
            logger.warning(
                "Entrées corrompues filtrées du mapping "
                "(bug engine : NER sur texte post-custom_rules) : %s",
                corrupted,
            )
        return clean
