from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = (
        "postgresql+psycopg://civil_engineering:civil_engineering@localhost:5432/civil_engineering"
    )
    local_storage_path: str = "./storage"
    cors_allowed_origins: str = "http://localhost:3000,http://localhost:3001,http://localhost:3002"
    # How long an archived project/file is kept before it's automatically,
    # permanently purged (manual purge from the admin panel remains available
    # at any time and is unaffected by this).
    archive_retention_days: int = 180
    # An archived item within this many days of its automatic purge date is
    # flagged (ProjectResponse/SourceFileResponse `purge_warning`) so it isn't
    # a surprise when it's swept.
    archive_purge_warning_days: int = 15
    # How long a purge-history entry (a record of something that was purged,
    # manually or automatically) is kept before it's deleted in turn.
    purge_history_retention_days: int = 365
    # How long a login session stays valid before it must be re-authenticated.
    session_ttl_days: int = 7

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    @property
    def cors_allowed_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
