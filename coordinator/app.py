"""App FastAPI du coordinateur — auth globale fail-closed, délègue à la boucle gatée.

Aucune route ne renvoie de valeur réelle : les résultats de la boucle sont déjà
tokenisés côté LLM ; les résultats d'exécution renvoyés à l'opérateur sont ceux de
l'agent (l'opérateur est autorisé). Plus de `/api/logs` (fuite PII de l'audit).
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from coordinator.loop import Completed, Denied, GatedLoop, LoopResult, Suspended
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
    return {"status": "failed", "reason": result.reason}


def build_app(*, loop: GatedLoop, auth_secret: str) -> FastAPI:
    """Construit l'app FastAPI du coordinateur avec auth globale fail-closed.

    L'assemblage runtime (clients UDS, politique YAML, session store chiffré,
    LLM du proposeur, point d'entrée uvicorn) relève du sous-projet D ; cette
    fabrique reçoit une `GatedLoop` déjà composée et un secret déjà chargé.
    """
    require_auth = make_auth_dependency(auth_secret)
    app = FastAPI(title="Cyber Coordinator", version="2.0")

    @app.get("/coordinator/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/coordinator/execute", dependencies=[Depends(require_auth)])
    async def execute(req: ExecuteRequest) -> dict[str, Any]:
        return _serialize(await loop.handle(req.request))

    @app.post("/coordinator/resume/{approval_id}", dependencies=[Depends(require_auth)])
    async def resume(approval_id: str) -> dict[str, Any]:
        return _serialize(await loop.resume(approval_id))

    @app.post("/coordinator/reject/{approval_id}", dependencies=[Depends(require_auth)])
    async def reject(approval_id: str) -> dict[str, Any]:
        return _serialize(loop.reject(approval_id))

    return app
