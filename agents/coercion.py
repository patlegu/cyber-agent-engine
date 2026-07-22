"""Coercition des arguments string CAP v2 vers les types déclarés par la fonction.

Les args CAP v2 sont toujours des strings (chaîne de confiance string de bout en
bout). Certaines fonctions attendent `int`/`bool`/`Literal`. On convertit selon la
signature, AVANT le dispatch, et on rejette proprement toute valeur non convertible
plutôt que de laisser crasher l'appel réel.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from typing import Any


class CoercionError(Exception):
    """Une valeur string ne peut pas être convertie vers le type déclaré."""


_TRUE = {"true", "1"}
_FALSE = {"false", "0"}


def _unwrap_optional(ann: Any) -> Any:
    if typing.get_origin(ann) in (typing.Union, __import__("types").UnionType):
        non_none = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return ann


def _coerce_one(name: str, value: str, ann: Any) -> Any:
    ann = _unwrap_optional(ann)
    if typing.get_origin(ann) is typing.Literal:
        allowed = [str(v) for v in typing.get_args(ann)]
        if value not in allowed:
            raise CoercionError(f"{name}={value!r} hors domaine {allowed}")
        return value
    if ann is int:
        try:
            return int(value)
        except ValueError as exc:
            raise CoercionError(f"{name}={value!r} n'est pas un entier") from exc
    if ann is bool:
        low = value.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise CoercionError(f"{name}={value!r} n'est pas un booléen")
    return value


def coerce_args(func: Callable[..., Any], args: dict[str, str]) -> dict[str, Any]:
    """Convertit `args` selon les annotations de `func`. Args non déclarés : inchangés."""
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return dict(args)
    hints = typing.get_type_hints(func)
    out: dict[str, Any] = {}
    for key, value in args.items():
        param = sig.parameters.get(key)
        if param is None:
            out[key] = value
            continue
        ann = hints.get(key, param.annotation)
        if ann is inspect.Parameter.empty:
            out[key] = value
        else:
            out[key] = _coerce_one(key, value, ann)
    return out
