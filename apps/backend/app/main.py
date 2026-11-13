from contextlib import asynccontextmanager
import secrets

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.agents import agents_router, departments_router
from app.api.artifacts import files_router as artifacts_files_router, router as artifacts_router
from app.api.brain import router as brain_router
from app.api.files import router as files_router
from app.api.inbox import router as inbox_router
from app.api.monitoring import router as monitoring_router
from app.api.projects import router as projects_router
from app.api.reviews import router as reviews_router
from app.api.settings import get_raw_secret, router as settings_router
from app.api.tasks import router as tasks_router
from app.api.ws import TaskWebSocketManager, router as ws_router
from app.config import AppSettings, get_settings
from app.db.session import init_db, seed_defaults
from app.orchestrator.graph import recover_interrupted_tasks


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Create and configure FastAPI application instance with security middleware."""
    resolved_settings = settings or get_settings()

    # Initialize SQLite database and seed defaults synchronously so non-lifespan
    # callers (e.g. TestClient without context manager) remain fully operational.
    factory = init_db(resolved_settings.resolved_db_path)
    with factory() as db_session:
        seed_defaults(db_session)

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        # Crash recovery on startup: move orphaned RUNNING tasks to PAUSED
        with factory() as startup_session:
            recovered_count = recover_interrupted_tasks(startup_session)
        app_instance.state.recovered_tasks_count = recovered_count
        app_instance.state.checkpoint_db_path = (
            resolved_settings.resolved_db_path.parent / "checkpoints.db"
        ).resolve()
        yield
        # Dispose SQLAlchemy engine connections cleanly on shutdown
        engine = factory.kw.get("bind")
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title="AI Agent Workspace Backend",
        version="0.1.0",
        description="FastAPI sidecar daemon for AI Agent Workspace (Văn Phòng AI)",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.session_factory = factory
    app.state.checkpoint_db_path = (
        resolved_settings.resolved_db_path.parent / "checkpoints.db"
    ).resolve()
    app.state.ws_manager = TaskWebSocketManager(
        extra_secrets=[resolved_settings.local_auth_token]
    )
    app.state.recovered_tasks_count = 0
    app.state.get_raw_secret = get_raw_secret

    # Mount API & WebSocket routers
    app.include_router(projects_router)
    app.include_router(tasks_router)
    app.include_router(agents_router)
    app.include_router(departments_router)
    app.include_router(artifacts_router)
    app.include_router(files_router)
    app.include_router(artifacts_files_router)
    app.include_router(brain_router)
    app.include_router(inbox_router)
    app.include_router(monitoring_router)
    app.include_router(reviews_router)
    app.include_router(settings_router)
    app.include_router(ws_router)

    # CORS configuration for desktop Next.js / Tauri shell
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "tauri://localhost",
            "http://tauri.localhost",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Local Auth Token enforcement middleware
    @app.middleware("http")
    async def enforce_local_auth_middleware(request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        # Enforce X-Local-Auth-Token on /api/v1/* endpoints (exempting webhooks)
        if request.url.path.startswith("/api/v1"):
            if request.url.path.startswith("/api/v1/inbox/webhook"):
                return await call_next(request)
            token = request.headers.get("X-Local-Auth-Token")
            if not token or not secrets.compare_digest(
                token.encode("utf-8"),
                resolved_settings.local_auth_token.encode("utf-8"),
            ):
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid or missing X-Local-Auth-Token"},
                )

        return await call_next(request)

    @app.get("/api/v1/health")
    async def health_check():
        return {
            "status": "ok",
            "service": "ai-agent-workspace-backend",
            "version": "0.1.0",
        }

    return app


app = create_app()


if __name__ == "__main__":
    import argparse
    import os
    import uvicorn

    parser = argparse.ArgumentParser(description="AI Agent Workspace Backend Daemon")
    parser.add_argument("--port", type=int, default=None, help="Port to listen on")
    parser.add_argument("--token", type=str, default=None, help="Local auth token")
    parser.add_argument("--workspace", type=str, default=None, help="Workspace directory")
    args, _ = parser.parse_known_args()

    if args.port:
        os.environ["BACKEND_PORT"] = str(args.port)
    if args.token:
        os.environ["LOCAL_AUTH_TOKEN"] = args.token
    if args.workspace:
        os.environ["WORKSPACE_DIR"] = args.workspace

    get_settings.cache_clear()
    runtime_settings = get_settings()
    uvicorn.run(
        create_app(runtime_settings),
        host="127.0.0.1",
        port=runtime_settings.backend_port,
        log_level="info",
    )
