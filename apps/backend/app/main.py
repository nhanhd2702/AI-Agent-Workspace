from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.agents import agents_router, departments_router
from app.api.artifacts import router as artifacts_router
from app.api.tasks import router as tasks_router
from app.config import AppSettings, get_settings
from app.db.session import init_db, seed_defaults


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Create and configure FastAPI application instance with security middleware."""
    resolved_settings = settings or get_settings()

    app = FastAPI(
        title="AI Agent Workspace Backend",
        version="0.1.0",
        description="FastAPI sidecar daemon for AI Agent Workspace (Văn Phòng AI)",
    )
    app.state.settings = resolved_settings

    # Initialize SQLite database and seed defaults for the active settings
    factory = init_db(resolved_settings.resolved_db_path)
    with factory() as db_session:
        seed_defaults(db_session)

    # Mount API routers
    app.include_router(tasks_router)
    app.include_router(agents_router)
    app.include_router(departments_router)
    app.include_router(artifacts_router)

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

        # Enforce X-Local-Auth-Token on /api/v1/* endpoints
        if request.url.path.startswith("/api/v1"):
            token = request.headers.get("X-Local-Auth-Token")
            if not token or token != resolved_settings.local_auth_token:
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
