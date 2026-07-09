# Universal AI Web Scraper Platform

Платформа для автоматического сбора, AI-обработки и экспорта данных с публичных сайтов.
Реализовано согласно ТЗ v2 (Этап 1 полностью, заготовки для Этапа 2/3).

## Что уже работает

- ✅ Регистрация/логин (JWT)
- ✅ Создание проекта с **SSRF-защитой** URL (блокирует внутренние/приватные адреса)
- ✅ Уважение `robots.txt` по умолчанию
- ✅ Краулер: per-domain rate limit, retry с backoff, circuit breaker при сериях ошибок
- ✅ Универсальный экстрактор (JSON-LD → og:-теги → эвристика по тексту)
- ✅ Дедупликация через `UNIQUE(project_id, source_url)` + `content_hash` — повторный запуск не плодит дубли
- ✅ Экспорт в Excel/CSV/JSON с защитой от formula injection
- ✅ Live-прогресс через WebSocket + Redis pub/sub
- ✅ AI-модули: очистка/категоризация и перевод (OpenAI), с БД-кэшем переводов и оценкой стоимости перед запуском
- ✅ Health-check `/health` для Railway
- ✅ CI (GitHub Actions): lint + tests на каждый push

## Что нужно доделать (Этап 2/3, см. ТЗ v2)

- Graceful cancel парсинга (сейчас `/stop` — best-effort, помечает статус, но не прерывает текущий HTTP-запрос воркера)
- Alembic-миграции (сейчас таблицы создаются через `Base.metadata.create_all()` при старте — ок для MVP, для прода настройте `alembic init` с `target_metadata = Base.metadata`)
- Прокси-пул для антиблокировки (заготовка в `app/scraper/antiblock.py`, сам пул нужно подключить)
- Реальная загрузка картинок в S3 из pipeline краулера (клиент готов в `app/storage/s3_client.py`, но не вызывается автоматически — подключите в `app/workers/tasks.py`)
- Лимиты/квоты по пользователю (`User.api_quota` в модели есть, проверка при старте парсинга — TODO)

## Быстрый старт локально

```bash
cp .env.example .env
# заполните .env — минимум DATABASE_URL, REDIS_URL; OPENAI_API_KEY для AI-функций

docker-compose up --build
```

Откройте http://localhost:8000

Воркер (`worker` сервис в docker-compose) поднимется автоматически и будет слушать очередь `scraper_tasks`.

## Локально без Docker

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# нужны локально запущенные Postgres и Redis, либо docker-compose up db redis

uvicorn app.main:app --reload
# в отдельном терминале:
rq worker scraper_tasks --url redis://localhost:6379/0
# либо (эквивалентно, но так же надёжнее на Railway - см. ниже):
python -m app.workers.worker_entrypoint
```

## Тесты

```bash
pytest tests/ -v
```

Обязательно прогоняйте `tests/test_ssrf_guard.py` перед любым изменением `app/scraper/ssrf_guard.py` — это самый критичный модуль безопасности проекта.

## Деплой на Railway

1. Запушьте репозиторий на GitHub (см. инструкцию ниже).
2. На [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**.
3. Добавьте плагины **PostgreSQL** и **Redis** через Railway (Railway сам пропишет `DATABASE_URL`/`REDIS_URL` — проверьте совпадение имён переменных с `config.py`, при необходимости переименуйте).
4. Задайте остальные ENV-переменные из `.env.example` (`OPENAI_API_KEY`, `JWT_SECRET` — сгенерируйте случайную строку, `S3_*` — если используете хранилище картинок).
5. Railway подхватит `railway.json` — билд через Dockerfile, healthcheck на `/health`.
6. **Важно**: для воркера создайте **второй сервис** в том же Railway-проекте (тот же репозиторий), со Start Command:
   ```
   python -m app.workers.worker_entrypoint
   ```
   (не `rq worker scraper_tasks --url $REDIS_URL` — эта форма ломается на Railway, если переменная не разворачивается в shell или не привязана к сервису; Python-entrypoint читает `REDIS_URL` напрямую и явно скажет в логах, если она не задана). Без отдельного воркер-сервиса парсинг не будет выполняться — задачи будут просто копиться в очереди.
   **Также проверьте**: переменная `REDIS_URL` (ссылка на Redis-плагин, например `${{Redis.REDIS_URL}}`) должна быть добавлена в Variables **именно этого** worker-сервиса — привязка к сервису web на него не распространяется автоматически.

## Как загрузить этот проект на GitHub

```bash
cd universal_scraper
git init
git add .
git commit -m "Initial commit: MVP Этап 1"
git branch -M main
git remote add origin https://github.com/ВАШ_ЛОГИН/universal-scraper.git
git push -u origin main
```

Если просит логин — используйте Personal Access Token вместо пароля (GitHub → Settings → Developer settings → Personal access tokens).

## Структура проекта

```
app/
├── main.py                 # FastAPI entrypoint
├── database.py             # SQLAlchemy engine/session
├── models.py                # User, Project, Page, Item, Translation
├── schemas.py                # Pydantic-схемы
├── security.py                # JWT auth
├── api/
│   ├── auth_routes.py
│   ├── project_routes.py
│   ├── export_routes.py
│   └── ws_routes.py           # live-прогресс
├── scraper/
│   ├── ssrf_guard.py           # 🔒 критичный модуль безопасности
│   ├── robots.py
│   ├── antiblock.py
│   ├── crawler.py
│   └── extractor.py
├── ai/
│   ├── analyzer.py             # очистка + категоризация
│   ├── translator.py           # перевод с БД-кэшем
│   └── cost_guard.py           # оценка стоимости
├── workers/
│   ├── queue.py                 # RQ
│   ├── tasks.py                  # основная задача краулинга
│   ├── db_sync.py
│   └── progress.py                # Redis pub/sub для WebSocket
├── exports/
│   └── exporter.py                 # Excel/CSV/JSON + защита от formula injection
└── storage/
    └── s3_client.py                 # object storage для картинок
```

## Безопасность — что важно не сломать при доработке

- **Никогда** не убирайте вызов `assert_url_is_safe()` перед HTTP-запросами краулера — это защита от SSRF (сервер не должен фетчить внутренние адреса по указке пользователя).
- Секреты только через ENV, никогда не коммитьте `.env` (уже в `.gitignore`).
- Экспорт в Excel/CSV обязательно проходит через `_sanitize_cell()` — иначе данные с сайта могут содержать вредоносную "формулу", которая выполнится при открытии файла.
