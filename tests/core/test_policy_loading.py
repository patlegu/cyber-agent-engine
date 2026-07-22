import pytest

from core.policy.catalog import Capability, CapabilityCatalog, MissingArgs, UnknownCapability
from core.policy.loading import PolicyError, load_policy
from core.policy.models import Intention


def _catalog() -> CapabilityCatalog:
    return CapabilityCatalog([
        Capability(name="opnsense.add_nat", required_args=["interface", "port"]),
        Capability(name="crowdsec.get_decisions"),
    ])


def test_validate_intention_ok() -> None:
    _catalog().validate_intention(Intention(capability="opnsense.add_nat", args={"interface": "lan", "port": "443"}))


def test_capacite_inconnue_leve() -> None:
    with pytest.raises(UnknownCapability):
        _catalog().validate_intention(Intention(capability="opnsense.reboot"))


def test_args_requis_manquant_leve() -> None:
    with pytest.raises(MissingArgs):
        _catalog().validate_intention(Intention(capability="opnsense.add_nat", args={"interface": "lan"}))


def test_load_policy_valide() -> None:
    raw = [{"match": {"capability": "opnsense.add_*"}, "effect": "approve", "reason": "r"}]
    rules = load_policy(raw, _catalog())
    assert len(rules) == 1 and rules[0].effect == "approve"


def test_load_policy_regle_malformee_leve() -> None:
    with pytest.raises(PolicyError):
        load_policy([{"match": {"capability": "x"}, "effect": "MAYBE"}], _catalog())


def test_load_policy_glob_ne_matche_aucune_capacite_leve() -> None:
    # Typo de l'operateur : glob qui ne couvre aucune capacite connue -> fail-closed au demarrage.
    with pytest.raises(PolicyError):
        load_policy([{"match": {"capability": "opnsens.add_*"}, "effect": "allow"}], _catalog())
