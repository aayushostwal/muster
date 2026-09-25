"""Runtime configuration, resolved from env vars / ~/.muster/config.yaml equivalents."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

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
    git_bin: str = "git"
    gh_bin: str = "gh"

    # PR delivery: per-subprocess timeouts (seconds).
    pr_git_timeout_seconds: int = 30
    pr_validation_timeout_seconds: int = 900
    pr_provider_timeout_seconds: int = 60

    # Retry / backoff for transient failures (session/usage limit, network).
    retry_base_seconds: int = 30
    retry_max_seconds: int = 900
    retry_max_attempts: int = 8

    # Agent subprocess safety limits. A backend that stops emitting structured
    # events must not leave a task looking live forever.
    runtime_startup_timeout_seconds: float = 60
    runtime_idle_timeout_seconds: float = 1200
    runtime_max_seconds: float = 7200
    runtime_watchdog_interval_seconds: float = 5
    runtime_stream_limit_bytes: int = 8 * 1024 * 1024

    # Interactive PTY terminals are opt-in until the local-only security and
    # lifecycle path has been validated on the host. Existing/cron tasks keep
    # using the structured runner regardless of this default.
    interactive_terminal_enabled: bool = False
    default_task_runtime_mode: Literal["structured", "interactive"] = "structured"
    terminal_allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
    terminal_replay_bytes: int = 2 * 1024 * 1024
    terminal_client_queue_frames: int = 256

    @property
    def terminal_allowed_origin_set(self) -> set[str]:
        return {origin.strip() for origin in self.terminal_allowed_origins.split(",") if origin.strip()}

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

    @property
    def backend_sessions_dir(self) -> Path:
        return self.data_dir / "backend-sessions"

    @property
    def terminals_dir(self) -> Path:
        return self.data_dir / "terminals"

    def ensure_dirs(self) -> None:
        for d in (
            self.data_dir,
            self.transcripts_dir,
            self.media_dir,
            self.backend_sessions_dir,
            self.terminals_dir,
            self.secret_key_file.parent,
        ):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
