import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.startup import StartupSanityReport, build_startup_sanity_report
from app.db.session import create_database_engine, initialize_database, session_factory
from app.render_repository import RenderExecutionRepository
from app.repositories import (
    InMemoryBatchRepository,
    InMemoryConfigurationRepository,
    SqlAlchemyBatchRepository,
    SqlAlchemyConfigurationRepository,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    sanity = build_startup_sanity_report()
    for warning in sanity["warnings"]:
        logger.warning("Startup sanity check: %s", warning)
    engine = create_database_engine()
    initialize_database(engine)
    if engine is None:
        app.state.batch_repository = InMemoryBatchRepository()
        app.state.configuration_repository = InMemoryConfigurationRepository()
        app.state.render_repository = None
    else:
        app.state.batch_repository = SqlAlchemyBatchRepository(session_factory(engine))
        app.state.configuration_repository = SqlAlchemyConfigurationRepository(
            session_factory(engine)
        )
        app.state.render_repository = RenderExecutionRepository(session_factory(engine))
    yield


app = FastAPI(
    title="UGC Creator API",
    version="0.1.0",
    description="Provider-neutral API for UGC video generation.",
    lifespan=lifespan,
)
app.state.batch_repository = InMemoryBatchRepository()
app.state.configuration_repository = InMemoryConfigurationRepository()
app.state.render_repository = None

app.include_router(router)


@app.get("/health", tags=["health"])
async def health() -> StartupSanityReport:
    return build_startup_sanity_report()
