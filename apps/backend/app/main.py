from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import AppSettings, get_settings


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Create and configure FastAPI application instance with security middleware."""
    resolved_settings = settings or get_settings()

    app = FastAPI(
        title="AI Agent Workspace Backend",
        version="0.1.0",
        description="FastAPI sidecar daemon for AI Agent Workspace (Văn Phòng AI)",
    )
    app.state.settings = resolved_settings

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
