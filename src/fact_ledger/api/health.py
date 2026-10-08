"""Liveness, readiness and version endpoints."""

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from fact_ledger import __version__
from fact_ledger.store.db import ping

router = APIRouter(tags=["ops"])


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]


class Version(BaseModel):
    version: str


@router.get("/health")
def health(request: Request, response: Response) -> Health:
    try:
        database_ok = ping(request.app.state.engine)
    except SQLAlchemyError:
        database_ok = False
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Health(status="degraded", database="unavailable")
    return Health(status="ok", database="ok")


@router.get("/version")
def version() -> Version:
    return Version(version=__version__)
