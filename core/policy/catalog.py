"""Catalogue de capacités — figé et vérifié au démarrage (pas rechargé à chaud).

``evaluate`` a besoin d'un référentiel stable pour que l'opérateur écrive des
règles fiables et pour rejeter une intention citant une capacité inexistante.
Un agent qui changerait ses capacités en cours de route déplacerait le sol sous
la politique — d'où le gel au démarrage.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.policy.models import Intention


class UnknownCapability(Exception):
    """L'intention cite une capacité absente du catalogue."""


class MissingArgs(Exception):
    """L'intention omet un argument requis par la capacité."""


class Capability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    required_args: list[str] = Field(default_factory=list)


class CapabilityCatalog:
    """Index nom→capacité, immuable après construction."""

    def __init__(self, caps: list[Capability]) -> None:
        self._by_name: dict[str, Capability] = {c.name: c for c in caps}

    def get(self, name: str) -> Capability | None:
        return self._by_name.get(name)

    def names(self) -> list[str]:
        return list(self._by_name)

    def validate_intention(self, intention: Intention) -> None:
        cap = self._by_name.get(intention.capability)
        if cap is None:
            raise UnknownCapability(intention.capability)
        missing = [a for a in cap.required_args if a not in intention.args]
        if missing:
            raise MissingArgs(f"{intention.capability}: {missing}")
