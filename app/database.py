"""
Настройка подключения к PostgreSQL через SQLAlchemy (async).
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

from config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()


async def get_db():
    """FastAPI dependency: даёт сессию БД и гарантированно закрывает её."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """
    Создаёт таблицы при старте (для быстрого MVP).
    В проде — заменить на Alembic-миграции (см. README, раздел Migrations).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
