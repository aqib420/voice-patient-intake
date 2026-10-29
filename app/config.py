from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/patients"
    vapi_webhook_secret: str = ""
    seed_data: bool = True
    log_level: str = "INFO"

    @property
    def sqlalchemy_url(self) -> str:
        """Railway/Heroku hand out postgres:// or postgresql:// URLs; SQLAlchemy
        needs the driver spelled out to use psycopg v3."""
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
