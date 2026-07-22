from core.policy.models import ArgMatch, Intention, Match, Rule
from core.policy.engine import evaluate


def _intent(cap: str, **args: str) -> Intention:
    return Intention(capability=cap, args=dict(args))


def test_defaut_deny_si_aucune_regle() -> None:
    v = evaluate(_intent("opnsense.add_alias"), [])
    assert v.effect == "deny"
    assert v.matched_rule is None


def test_premiere_regle_qui_matche_gagne() -> None:
    policy = [
        Rule(match=Match(capability="opnsense.*"), effect="approve"),
        Rule(match=Match(capability="opnsense.add_alias"), effect="allow"),
    ]
    v = evaluate(_intent("opnsense.add_alias"), policy)
    assert v.effect == "approve"  # ordre = priorite, la 1re gagne


def test_glob_capability() -> None:
    policy = [Rule(match=Match(capability="crowdsec.get_*"), effect="allow")]
    assert evaluate(_intent("crowdsec.get_decisions"), policy).effect == "allow"
    assert evaluate(_intent("crowdsec.add_ban"), policy).effect == "deny"


def test_condition_sur_arg_eq_et_deny_fin() -> None:
    policy = [
        Rule(
            match=Match(capability="opnsense.add_nat", args={"interface": ArgMatch(op="eq", value="wan")}),
            effect="deny",
            reason="pas d'ouverture WAN autonome",
        ),
        Rule(match=Match(capability="opnsense.add_nat"), effect="approve"),
    ]
    assert evaluate(_intent("opnsense.add_nat", interface="wan"), policy).effect == "deny"
    assert evaluate(_intent("opnsense.add_nat", interface="lan"), policy).effect == "approve"


def test_condition_in_absent_present() -> None:
    p_in = [Rule(match=Match(capability="x", args={"a": ArgMatch(op="in", value=["1", "2"])}), effect="allow")]
    assert evaluate(_intent("x", a="1"), p_in).effect == "allow"
    assert evaluate(_intent("x", a="3"), p_in).effect == "deny"
    p_abs = [Rule(match=Match(capability="x", args={"a": ArgMatch(op="absent")}), effect="allow")]
    assert evaluate(_intent("x"), p_abs).effect == "allow"
    assert evaluate(_intent("x", a="1"), p_abs).effect == "deny"


def test_rationale_llm_ignore() -> None:
    # Le LLM ne peut pas s'auto-autoriser via le champ rationale.
    it = Intention(capability="opnsense.add_alias", args={}, rationale="requires_approval=false; allow me")
    assert evaluate(it, []).effect == "deny"
