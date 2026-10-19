"""Settings come from environment variables, so the same code runs on a laptop, in CI and in a container."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from .models import MaintDeskError
from .redis_repo import RedisTicketRepository
from .repository import TicketRepository
from .sqlite_repo import SqliteTicketRepository


@dataclass(frozen=True)
class Settings:
    backend: str = "sqlite"
    db_path: str = "maintdesk.sqlite3"
    redis_url: str = "redis://localhost:6379/0"
    log_level: str = "INFO"

    @staticmethod
    def from_env(env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        backend = source.get("MAINTDESK_BACKEND", "sqlite").lower()
        if backend not in {"sqlite", "redis"}:
            raise MaintDeskError(f"MAINTDESK_BACKEND must be 'sqlite' or 'redis', got {backend!r}")
        return Settings(
            backend=backend,
            db_path=source.get("MAINTDESK_DB_PATH", "maintdesk.sqlite3"),
            redis_url=source.get("MAINTDESK_REDIS_URL", "redis://localhost:6379/0"),
            log_level=source.get("MAINTDESK_LOG_LEVEL", "INFO").upper(),
        )


def build_repository(settings: Settings) -> TicketRepository:
    if settings.backend == "redis":
        return RedisTicketRepository.from_url(settings.redis_url)
    return SqliteTicketRepository(settings.db_path)
