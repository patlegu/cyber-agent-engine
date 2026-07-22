import pytest

from core.auth.api_key import AuthNotConfigured, load_auth_secret, verify


def test_load_secret_absent_leve() -> None:
    with pytest.raises(AuthNotConfigured):
        load_auth_secret({})


def test_load_secret_vide_leve() -> None:
    with pytest.raises(AuthNotConfigured):
        load_auth_secret({"COORDINATOR_API_KEY": ""})


def test_load_secret_present() -> None:
    assert load_auth_secret({"COORDINATOR_API_KEY": "s3cret"}) == "s3cret"


def test_verify() -> None:
    assert verify("s3cret", "s3cret") is True
    assert verify("wrong", "s3cret") is False
    assert verify(None, "s3cret") is False


def test_toutes_les_routes_portent_la_dependance_auth() -> None:
    from fastapi import Depends, FastAPI

    from core.auth.api_key import make_auth_dependency

    dep = make_auth_dependency("s3cret")
    app = FastAPI(dependencies=[Depends(dep)])  # dépendance GLOBALE

    @app.get("/api/status")
    def _status() -> dict[str, str]:
        return {"ok": "1"}

    # Introspection : chaque route applicative doit référencer la dépendance globale.
    from starlette.routing import Route

    app_routes = [r for r in app.routes if isinstance(r, Route) and r.path.startswith("/api")]
    assert app_routes, "au moins une route applicative"
    for route in app_routes:
        dep_calls = [d.call for d in route.dependant.dependencies]
        assert dep in dep_calls, f"route {route.path} sans dépendance d'auth"


def test_dependance_rejette_une_cle_absente_ou_fausse() -> None:
    import pytest
    from fastapi import HTTPException

    from core.auth.api_key import make_auth_dependency

    require = make_auth_dependency("s3cret")
    require("s3cret")  # cle correcte : ne leve pas
    for bad in (None, "wrong"):
        with pytest.raises(HTTPException) as exc:
            require(bad)
        assert exc.value.status_code == 401
