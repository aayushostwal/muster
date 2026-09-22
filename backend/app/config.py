"""Runtime configuration, resolved from env vars / ~/.muster/config.yaml equivalents."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MUSTER_", env_file=".env", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "muster"
    postgres_password: str = "muster"
    postgres_db: str = "muster"

    data_dir: Path = Path.home() / ".muster" / "data"
    secret_key_file: Path = Path.home() / ".muster" / "secret.key"

    api_host: str = "0.0.0.0"
    api_port: int = 8080

    claude_code_bin: str = "claude"
    codex_bin: str = "codex"

    # Retry / backoff for transient failures (session/usage limit, network).
    retry_base_seconds: int = 30
    retry_max_seconds: int = 900
    retry_max_attempts: int = 8

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def transcripts_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.transcripts_dir, self.media_dir, self.secret_key_file.parent):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
