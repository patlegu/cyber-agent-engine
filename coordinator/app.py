"""App FastAPI du coordinateur — auth globale fail-closed, délègue à la boucle gatée.

Aucune route ne renvoie de valeur réelle : les résultats de la boucle sont déjà
tokenisés côté LLM ; les résultats d'exécution renvoyés à l'opérateur sont ceux de
l'agent (l'opérateur est autorisé). Plus de `/api/logs` (fuite PII de l'audit).

`build_app` reçoit une `GatedLoop` déjà composée (tests, ou tout appelant qui
assemble sa propre boucle) ; les routes lisent la boucle sur `request.app.state.loop`,
posée soit directement par `build_app`, soit par le `lifespan` de
`create_default_app`. Ce module n'importe donc jamais lui-même de client réseau
ni de moteur LLM au niveau module : l'assemblage (`assemble_loop`, ouverture du
client d'agent, init du LLM) n'a lieu qu'au démarrage effectif de l'app, dans le
`lifespan` — `import coordinator.app` reste léger.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel

from coordinator.assembly import assemble_loop
from coordinator.clients.tool_agent_client import ToolAgentClient
from coordinator.config import load_config
from coordinator.llm.coordinator_llm import CoordinatorLLM
from coordinator.loop import Completed, Denied, Failed, GatedLoop, LoopResult, Suspended
from core.auth.api_key import make_auth_dependency


class ExecuteRequest(BaseModel):
    request: str


def _serialize(result: LoopResult) -> dict[str, Any]:
    if isinstance(result, Completed):
        return {"status": "completed", "summary": result.summary, "results": result.results}
    if isinstance(result, Suspended):
        return {"status": "pending_approval", "approval_id": result.approval_id}
    if isinstance(result, Denied):
        return {"status": "denied", "reason": result.reason}
    if isinstance(result, Failed):
        return {"status": "failed", "reason": result.reason}
    raise TypeError(f"variante LoopResult non sérialisée : {type(result).__name__}")


def _register_routes(app: FastAPI, auth_secret: str) -> None:
    """Enregistre les routes ; elles lisent la boucle sur `app.state.loop`.

    Indirection nécessaire pour `create_default_app` : au moment où les routes
    sont enregistrées, la boucle n'existe pas encore — elle n'est posée que
    plus tard par le `lifespan`, une fois l'assemblage réseau terminé. Lire
    `request.app.state.loop` à chaque appel (plutôt que de fermer sur une
    variable locale) garantit qu'on voit toujours la boucle courante.
    """
    require_auth = make_auth_dependency(auth_secret)

    @app.get("/coordinator/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/coordinator/execute", dependencies=[Depends(require_auth)])
    async def execute(req: ExecuteRequest, request: Request) -> dict[str, Any]:
        return _serialize(await request.app.state.loop.handle(req.request))

    @app.post("/coordinator/resume/{approval_id}", dependencies=[Depends(require_auth)])
    async def resume(approval_id: str, request: Request) -> dict[str, Any]:
        return _serialize(await request.app.state.loop.resume(approval_id))

    @app.post("/coordinator/reject/{approval_id}", dependencies=[Depends(require_auth)])
    async def reject(approval_id: str, request: Request) -> dict[str, Any]:
        return _serialize(request.app.state.loop.reject(approval_id))


def build_app(*, loop: GatedLoop, auth_secret: str) -> FastAPI:
    """Construit l'app FastAPI du coordinateur avec auth globale fail-closed.

    Reçoit une `GatedLoop` déjà composée et un secret déjà chargé : l'appelant
    (tests, ou tout assemblage alternatif) garde la main sur le câblage runtime.
    """
    app = FastAPI(title="Cyber Coordinator", version="2.0")
    app.state.loop = loop
    _register_routes(app, auth_secret)
    return app


def create_default_app() -> FastAPI:
    """Assemble l'app runtime depuis l'environnement (fail-closed sur secrets).

    `load_config` lève immédiatement si un secret/chemin obligatoire manque —
    avant toute tentative de connexion réseau. L'assemblage proprement dit
    (client d'agent, LLM, catalogue, politique) est différé au `lifespan` de
    l'app FastAPI, donc au démarrage effectif (uvicorn), jamais à l'import de
    ce module.
    """
    config = load_config(os.environ)  # lève si secrets/chemin manquants (au démarrage)

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = ToolAgentClient(
            base_url=config.agent_server_url,
            api_key=config.agent_server_key,
            socket_path=config.agent_server_sock,
        )
        # ToolAgentClient/CoordinatorLLM (autres sous-projets) ne sont pas
        # entièrement typés — no-untyped-call ignoré ponctuellement ici plutôt
        # que d'étendre le périmètre mypy strict à des modules hors scope.
        #
        # Le try démarre dès l'ouverture du client : si llm.init() ou
        # assemble_loop() lève, le client doit quand même être fermé (sinon
        # fuite de socket). llm n'est fermé que s'il a été initialisé avec
        # succès — un échec de llm.init() ne doit pas appeler shutdown() sur
        # un LLM à moitié construit.
        await client.__aenter__()  # type: ignore[no-untyped-call]
        llm = CoordinatorLLM()  # type: ignore[no-untyped-call]
        llm_initialized = False
        try:
            await llm.init()
            llm_initialized = True
            app.state.loop = await assemble_loop(config, client, llm)
            yield
        finally:
            await client.__aexit__(None, None, None)  # type: ignore[no-untyped-call]
            if llm_initialized:
                await llm.shutdown()

    app = FastAPI(title="Cyber Coordinator", version="2.0", lifespan=_lifespan)
    _register_routes(app, config.auth_secret)
    return app


def run() -> None:
    """Point d'entrée console : lance uvicorn sur l'app assemblée."""
    import uvicorn  # noqa: PLC0415 — import différé, réservé au point d'entrée console

    config = load_config(os.environ)
    uvicorn.run(create_default_app(), host=config.host, port=config.port)
