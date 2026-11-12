from functools import lru_cache
from pathlib import Path
from typing import Optional
from cryptography.fernet import Fernet
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Application settings for AI Agent Workspace backend runtime."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    workspace_dir: Path = Field(
        default_factory=lambda: Path("./workspace").resolve(),
        description="Path to local persistent workspace directory",
    )
    local_auth_token: str = Field(
        default="dev-local-token",
        description="Local shared secret token for authenticating frontend-backend calls",
    )
    backend_port: int = Field(
        default=8765,
        description="Local HTTP/WebSocket port for backend daemon",
    )
    max_workspace_bytes: int = Field(
        default=5 * 1024**3,
        description="Maximum storage allowed in workspace in bytes (default 5GB)",
    )
    encryption_key: bytes = Field(
        default_factory=Fernet.generate_key,
        description="Fernet symmetric encryption key for encrypting secrets at rest",
    )
    db_path: Optional[Path] = Field(
        default=None,
        description="Explicit path to SQLite database file. Defaults to workspace_dir/app.db",
    )
    chroma_dir: Optional[Path] = Field(
        default=None,
        description="Explicit directory for ChromaDB vector store. Defaults to workspace_dir/chroma",
    )

    @field_validator("workspace_dir", mode="before")
    @classmethod
    def parse_workspace_dir(cls, v: object) -> Path:
        if isinstance(v, str):
            return Path(v).resolve()
        if isinstance(v, Path):
            return v.resolve()
        return v  # type: ignore[return-value]

    @field_validator("encryption_key", mode="before")
    @classmethod
    def parse_encryption_key(cls, v: object) -> bytes:
        if isinstance(v, str):
            return v.encode("utf-8")
        if isinstance(v, bytes):
            return v
        return v  # type: ignore[return-value]

    @property
    def resolved_db_path(self) -> Path:
        if self.db_path is not None:
            return self.db_path.resolve()
        return (self.workspace_dir / "app.db").resolve()

    @property
    def resolved_chroma_dir(self) -> Path:
        if self.chroma_dir is not None:
            return self.chroma_dir.resolve()
        return (self.workspace_dir / "chroma").resolve()


@lru_cache
def get_settings() -> AppSettings:
    """Retrieve cached global AppSettings instance."""
    return AppSettings()
