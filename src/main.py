"""SceneSearch API — natural-language search over driving footage.

Startup loads the corpus and both text towers, and `/health` and `/status` answer different
questions once it has: `/health` is liveness, `/status` reports whether the artifacts are resident.

**The port is closed for the whole of that load — measured at ~36 s with a warm Hugging Face cache,
minutes without one.** uvicorn runs the lifespan handler *before* it binds the socket, so a request
during startup is `connection refused`, not a slow 200. This docstring used to claim the process
"binds its port and answers `/health` immediately"; that described the intent and not the behaviour,
and a teammate reading it diagnosed a `[vite] http proxy error` as a broken endpoint when the port
was simply not open yet. A platform health check must tolerate that window — `Dockerfile`'s
`HEALTHCHECK` allows for it with `--start-period=90s`.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.admin import admin_router
from src.api.auth import auth_router
from src.api.history import history_router
from src.api.routes import router
from src.api.users import users_router
from src.config import get_settings
from src.models.schemas import HealthResponse

logger = logging.getLogger(__name__)
settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

VERSION = "0.1.0"


def _configure_tracing() -> None:
    """Point LangChain at LangSmith, if it is switched on.

    Set through the environment because that is the only interface LangChain reads. The key comes
    from settings so it stays out of the source, and tracing is off by default so a local run never
    silently ships queries to a hosted service.
    """
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        return
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    logger.info("LangSmith tracing enabled, project=%s", settings.langsmith_project)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_tracing()
    try:
        from src.services.search.artifacts import get_corpus
        from src.services.search.encoder import warmup

        corpus = get_corpus()
        logger.info("corpus loaded: %d frames (%s)", corpus.n_frames, corpus.provenance.get("encoder"))
        warmup()
        logger.info("text encoders warm")
    except (FileNotFoundError, ValueError, ImportError, OSError) as exc:
        # Serve anyway: /health stays up and /status reports 503, which is far easier to diagnose
        # from outside than a container that exits on boot.
        logger.error("startup could not load the corpus or encoders: %s", exc)

    # PostgreSQL tables — idempotent, so restarts are safe.
    try:
        from src.db.init_db import init_db

        init_db()
        logger.info("PostgreSQL tables initialised")
    except Exception as exc:
        logger.error("startup could not initialise PostgreSQL: %s", exc)

    yield
    logger.info("shutting down")


app = FastAPI(
    title="SceneSearch",
    description="Natural-language search over driving-footage keyframes, with an honest "
    "'nothing matches' when the archive does not contain what was asked for.",
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(history_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness. Must stay cheap and dependency-free — the deploy's uptime check calls it."""
    try:
        from src.services.search.artifacts import get_corpus

        frames = get_corpus().n_frames
    except (FileNotFoundError, ValueError):
        frames = 0
    return HealthResponse(status="ok", version=VERSION, corpus_frames=frames, release=get_settings().release)


def _mount_frontend() -> None:
    """Serve the built frontend from the same origin as the API, when it has been built.

    Registered *after* the router and the health route, so a static file can never shadow an
    endpoint: FastAPI matches in registration order and this catch-all would otherwise swallow
    everything.

    Same-origin is the point, not a convenience. It removes CORS from the deployment entirely —
    `docs/api-contract.md` warns that a frontend on a different origin must be added to
    `CORS_ORIGINS` or every browser request 403s, and the failure shows up only once deployed.
    Serving both from one process means there is no origin to configure and nothing to get wrong.

    Absent in development: `npm run dev` serves the frontend on :5173 and proxies `/api` here, so
    this is a no-op unless `FE/dist` exists. That keeps a missing build a silent non-feature rather
    than a startup crash.
    """
    dist = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "FE", "dist")
    if not os.path.isdir(dist):
        logger.info("no FE/dist — serving the API only (run `npm run build` to include the UI)")
        return

    from fastapi.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException as StarletteHTTPException

    class SPAStatic(StaticFiles):
        """StaticFiles that serves `index.html` for client-side routes.

        `html=True` alone only covers directory requests, so `/archive` — a real route in
        `FE/src/router/index.tsx`, reached through `BrowserRouter` and therefore a genuine URL a
        user can bookmark or refresh — returns 404 without this.

        Two exclusions, both load-bearing:

        **`api/` never falls back.** A catch-all mounted at `/` receives every unmatched path,
        including API typos and hostile ones. Serving HTML for those turns `GET /api/v1/nope` into a
        200 and — caught by `test_thumbnail_rejects_anything_that_is_not_a_frame_id` — turned the
        path-traversal probes the thumbnail route is hardened against from 404 into 200. A security
        control that silently stops returning 404 is worse than one that never existed.

        **Paths with an extension never fall back.** A missing `/assets/index-abc123.js` should stay
        a 404: answering it with HTML turns an asset that failed to deploy into a page that loads and
        then breaks in the console, which is far harder to diagnose than a missing file.
        """

        async def get_response(self, path: str, scope):
            # Decisions are made on scope["path"], the raw URL, not on `path`. Starlette builds the
            # latter with os.path.normpath, so on Windows it arrives back-slashed — "api\\v1\\nope"
            # — and a startswith("api/") check would pass in the Linux container while failing on a
            # developer's machine. A rule that holds on one platform is not a rule.
            #
            # Starlette *raises* HTTPException(404) here rather than returning a 404 response, so
            # inspecting a returned status code silently never fires either.
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                url = scope.get("path", "")
                looks_like_a_route = "." not in url.rsplit("/", 1)[-1]
                is_api = url == "/api" or url.startswith("/api/")
                if exc.status_code == 404 and looks_like_a_route and not is_api:
                    return await super().get_response("index.html", scope)
                raise

    app.mount("/", SPAStatic(directory=dist, html=True), name="frontend")
    logger.info("serving frontend from %s", dist)


_mount_frontend()
