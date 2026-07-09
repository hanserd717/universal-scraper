"""
Синхронная сессия БД для RQ worker.
RQ выполняет задачи в обычных (не async) процессах, поэтому для воркера
используем sync SQLAlchemy engine (psycopg2), а не asyncpg-движок из app/database.py.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import settings

# Заменяем asyncpg-драйвер на psycopg2 для синхронного использования в воркере
sync_url = settings.database_url.replace("+asyncpg", "")

sync_engine = create_engine(sync_url, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(bind=sync_engine)
