"""
Настройка подключения к PostgreSQL через SQLAlchemy (async).
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

from config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()

# Колонки, добавленные в Item ПОСЛЕ первого деплоя. create_all() не трогает уже
# существующие таблицы (только создаёт отсутствующие), поэтому на уже
# развёрнутой в проде БД эти колонки сами не появятся - нужен явный ALTER TABLE.
# Postgres 9.6+ поддерживает ADD COLUMN IF NOT EXISTS, так что это идемпотентно
# и безопасно гонять при каждом старте. Это не замена нормальным миграциям
# (Alembic) - временное решение для MVP, см. README.
ITEM_MIGRATION_COLUMNS = [
    ("slug", "VARCHAR"),
    ("tag", "VARCHAR"),
    ("status_ru", "VARCHAR"),
    ("status_en", "VARCHAR"),
    ("added_month", "VARCHAR"),
    ("clearnet_url", "VARCHAR"),
    ("tor_url", "VARCHAR"),
    ("app_store_url", "VARCHAR"),
    ("google_play_url", "VARCHAR"),
    ("telegram", "VARCHAR"),
    ("short_description_ru", "TEXT"),
    ("short_description_en", "TEXT"),
    ("full_description_ru", "TEXT"),
    ("full_description_en", "TEXT"),
    ("features", "TEXT"),
    ("official_website", "VARCHAR"),
    ("logo_url", "VARCHAR"),
    ("screenshot_url", "VARCHAR"),
    ("country", "VARCHAR"),
    ("language", "VARCHAR"),
    ("currencies", "VARCHAR"),
    ("payment_methods", "VARCHAR"),
    ("supported_cryptocurrencies", "VARCHAR"),
    ("email", "VARCHAR"),
    ("social_media", "VARCHAR"),
    ("review_count", "INTEGER"),
    ("data_source", "VARCHAR"),
    ("last_checked_at", "VARCHAR"),
    ("notes", "TEXT"),
]


async def get_db():
    """FastAPI dependency: даёт сессию БД и гарантированно закрывает её."""
    async with AsyncSessionLocal() as session:
        yield session


async def _migrate_item_columns(conn):
    for column_name, column_type in ITEM_MIGRATION_COLUMNS:
        await conn.execute(
            text(f"ALTER TABLE items ADD COLUMN IF NOT EXISTS {column_name} {column_type}")
        )


async def init_db():
    """
    Создаёт отсутствующие таблицы и докатывает новые колонки на уже
    существующие (см. ITEM_MIGRATION_COLUMNS выше). Для быстрого MVP;
    в проде на растущем проекте — заменить на Alembic-миграции.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_item_columns(conn)
