import asyncio
import functools
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apsui import __version__, migrate
from apsui.api import router as api_router
from apsui.apworlds import finish_apworld
from apsui.config import Settings, get_settings
from apsui.db import make_engine, make_sessionmaker
from apsui.jobs import JobQueue
from apsui.spa import SPAStaticFiles
from apsui.uploads import finish_yaml

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        engine = make_engine(settings.database_url)
        migrate.upgrade(engine)
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker = make_sessionmaker(engine)
        jobs = JobQueue(settings.resolved_jobs_dir)
        jobs.ensure()
        jobs.on_finished["validate-yaml"] = functools.partial(finish_yaml, settings=settings)
        jobs.on_finished["test-apworld"] = functools.partial(finish_apworld, settings=settings)
        app.state.jobs = jobs

        async def collect_jobs() -> None:
            def collect_once() -> None:
                with sessionmaker() as session:
                    jobs.collect(session)

            while True:
                try:
                    await asyncio.to_thread(collect_once)
                except Exception:
                    log.exception("collecting worker jobs failed")
                await asyncio.sleep(settings.job_poll_interval)

        collector = asyncio.create_task(collect_jobs())
        try:
            yield
        finally:
            collector.cancel()
            engine.dispose()

    app = FastAPI(title="Archipelago Server UI", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.include_router(api_router)

    static_dir = settings.resolved_static_dir
    if static_dir is None:
        log.warning("Frontend not built; serving the API only. Run `npm run build` in frontend/.")
    else:
        app.mount("/", SPAStaticFiles(directory=static_dir), name="frontend")

    return app
