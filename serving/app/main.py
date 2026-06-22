"""FastAPI entry for the Harbormaster serving plane.

Deterministic AIS anomaly scoring: zero-token live path, observability-first.
Routes mirror the GeoTrace front door (/healthz, /metrics, /v1/feedback) with the
new /v1/score-ais scoring endpoint and a /v1/hitl/pending view for the reviewer
console.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import __version__
from app.config import get_settings
from app.errors import HarbormasterError
from app.models import AisScoreIn, AisScoreOut, FeedbackIn, FeedbackOut, HealthOut
from app.orchestrator import Orchestrator

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.orchestrator = await Orchestrator.bootstrap(settings)
    log.info("startup", env=settings.env, version=settings.version)
    try:
        yield
    finally:
        await app.state.orchestrator.shutdown()
        log.info("shutdown")


app = FastAPI(title="Harbormaster-Serving", version=__version__, lifespan=lifespan)


@app.exception_handler(HarbormasterError)
async def harbormaster_error_handler(_: Request, err: HarbormasterError) -> JSONResponse:
    return JSONResponse(
        status_code=err.http_status,
        content={"code": err.code, "message": err.message, "context": err.context},
    )


@app.get("/healthz", response_model=HealthOut)
async def healthz() -> HealthOut:
    return HealthOut(status="ok", version=app.version)


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/score-ais", response_model=AisScoreOut)
async def v1_score_ais(payload: AisScoreIn, request: Request) -> AisScoreOut:
    orch: Orchestrator = request.app.state.orchestrator
    return await orch.score(payload)


@app.post("/v1/feedback", response_model=FeedbackOut)
async def v1_feedback(payload: FeedbackIn, request: Request) -> FeedbackOut:
    orch: Orchestrator = request.app.state.orchestrator
    return await orch.record_feedback(payload)


@app.get("/v1/hitl/pending")
async def v1_hitl_pending(request: Request) -> list[dict]:
    orch: Orchestrator = request.app.state.orchestrator
    rows = await orch.hitl.pending()
    # ts / created_at may be datetimes; ORJSON handles them, keep as-is.
    return rows


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
