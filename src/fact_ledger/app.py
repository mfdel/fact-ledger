"""Composition root: builds the FastAPI application and wires its dependencies."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from fact_ledger import __version__
from fact_ledger.api import health
from fact_ledger.settings import Settings, get_settings
from fact_ledger.store.db import make_engine
from fact_ledger.web import pages


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(title="Fact Ledger", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.include_router(health.router)
    app.include_router(pages.router)
    return app
