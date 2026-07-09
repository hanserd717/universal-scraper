"""
Точка входа FastAPI-приложения.
Запуск локально: uvicorn app.main:app --reload
Запуск воркера (отдельным процессом): python -m app.workers.worker_entrypoint
"""
import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.requests import Request

from config import settings, looks_like_unlinked_variable
from app.database import init_db, engine
from app.api.auth_routes import router as auth_router
from app.api.project_routes import router as project_router
from app.api.export_routes import router as export_router
from app.api.ws_routes import router as ws_router
from app.api.catalog_routes import router as catalog_router

logging.basicConfig(level=settings.log_level)

app = FastAPI(title="Universal AI Web Scraper Platform")

app.include_router(auth_router)
app.include_router(project_router)
app.include_router(export_router)
app.include_router(ws_router)
app.include_router(catalog_router)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def on_startup():
    # MVP: авто-создание таблиц. В проде — заменить на `alembic upgrade head`.
    # Важно: не роняем всё приложение, если БД временно недоступна (например,
    # Postgres ещё не поднялся при первом деплое) — иначе /health не сможет
    # даже ответить "degraded", контейнер просто не запустится вообще.
    try:
        await init_db()
    except Exception:
        logging.getLogger(__name__).exception(
            "Не удалось создать таблицы при старте — БД недоступна. "
            "Приложение всё равно запускается, /health покажет статус."
        )


@app.get("/health")
async def health_check():
    """Обязательный healthcheck для Railway — проверяет реальное соединение с БД."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
        hint = None
    except Exception:
        db_ok = False
        hint = (
            "DATABASE_URL указывает на localhost, но контейнер запущен на Railway — "
            "переменная не привязана к этому сервису. Добавьте её в Variables как "
            "ссылку на Postgres-плагин (Add Reference)."
            if looks_like_unlinked_variable(settings.database_url)
            else "Проверьте DATABASE_URL и доступность БД."
        )

    status_code = 200 if db_ok else 503
    content = {"status": "ok" if db_ok else "degraded", "database": db_ok}
    if hint:
        content["hint"] = hint

    return JSONResponse(content=content, status_code=status_code)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
