"""
Централизованная конфигурация проекта.
Все настройки читаются из переменных окружения (.env локально, ENV vars на Railway).
Никогда не хардкодить секреты здесь.
"""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import os


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://scraper:scraper@localhost:5432/scraper"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    ai_monthly_budget_usd: float = 20.0

    # Auth
    jwt_secret: str = "insecure-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # S3 / object storage
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "scraper-images"
    s3_region: str = "auto"

    # Crawler defaults
    default_max_pages: int = 500
    default_depth: int = 3
    default_delay_seconds: float = 1.0
    respect_robots_txt: bool = True

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        """
        Railway (и Heroku-style провайдеры) обычно выдают DATABASE_URL как
        `postgresql://...` или `postgres://...`, без указания async-драйвера.
        Наш код использует asyncpg — принудительно нормализуем префикс,
        чтобы не зависеть от того, в каком именно виде провайдер отдал переменную.
        """
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql://", 1)
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v


def running_on_railway() -> bool:
    """Railway всегда инжектит эту переменную в каждый контейнер сервиса."""
    return bool(os.environ.get("RAILWAY_ENVIRONMENT"))


def looks_like_unlinked_variable(url: str) -> bool:
    """
    Если мы на Railway, а URL всё ещё указывает на localhost/127.0.0.1 —
    почти наверняка нужная переменная (DATABASE_URL/REDIS_URL) не прилинкована
    к ЭТОМУ конкретному сервису, и код тихо откатился на дефолт из этого файла.
    Используется и для БД (app/database.py), и для Redis (app/workers/worker_entrypoint.py).
    """
    return running_on_railway() and ("localhost" in url or "127.0.0.1" in url)


settings = Settings()

