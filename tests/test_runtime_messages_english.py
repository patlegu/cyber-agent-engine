"""Garde-fou : aucun message opérateur runtime en français accentué.

Scanne (AST) les littéraux chaîne passés à `raise`, aux méthodes de logging
(debug/info/warning/warn/error/critical/exception/log), à `print`, et aux champs
de réponse opérateur `reason=`/`error=`, sur la surface first-party ; échoue si un
caractère accentué français y apparaît. Par construction, docstrings, prompts LLM,
descriptions d'outils et vocab classifier ne sont jamais inspectés (ce ne sont pas
ces appels).

Limite connue : le français SANS accent (« timeout serveur ») n'est pas détecté ;
le sweep initial en assure la complétude, ce test garde la régression du cas
courant (accentué)."""
import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DIRS = ("core", "coordinator", "agents", "clients")
_ROOT_FILES = ("server.py",)
_ACCENTS = set("éèàçêîôûïœÉÈÀÇÊÎÔÛÏŒëüö")
_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log"}
_RESPONSE_FIELDS = {"reason", "error"}


def _sources():
    files = []
    for d in _DIRS:
        files.extend((_ROOT / d).rglob("*.py"))
    files.extend(_ROOT / f for f in _ROOT_FILES)
    return files


def _call_name(func):
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _accented(node):
    return [
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and any(c in _ACCENTS for c in n.value)
    ]


def _offenders(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        strs = []
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            for a in node.exc.args:
                strs += _accented(a)
            for kw in node.exc.keywords:
                strs += _accented(kw.value)
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in _LOG_METHODS:
                for a in node.args:
                    strs += _accented(a)
                for kw in node.keywords:
                    strs += _accented(kw.value)
            elif name == "print":
                for a in node.args:
                    strs += _accented(a)
            for kw in node.keywords:
                if kw.arg in _RESPONSE_FIELDS:
                    strs += _accented(kw.value)
        for s in strs:
            found.append(f"{path.relative_to(_ROOT)}:{node.lineno}  {s[:60]!r}")
    return found


def test_no_french_operator_messages():
    offenders = []
    for path in _sources():
        offenders.extend(_offenders(path))
    assert not offenders, "messages opérateur FR accentués:\n" + "\n".join(offenders)
