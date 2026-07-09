"""
Точка входа для RQ worker.

Почему не `rq worker --url $REDIS_URL` (CLI): на Railway это ломается двумя
способами — (1) если Custom Start Command выполняется не через shell,
`$REDIS_URL` попадёт в команду буквально как текст, а не развернётся в
значение; (2) если переменная Redis-плагина привязана только к сервису web,
а не к отдельному сервису worker, `$REDIS_URL` развернётся в пустую строку.
В обоих случаях rq падает с `ValueError: Redis URL must specify one of the
following schemes`.

Через Python API мы читаем REDIS_URL из config.py (pydantic-settings сам
подхватывает переменную окружения независимо от shell) и явно проверяем,
что она задана и валидна, с понятным сообщением об ошибке, если нет.

Start Command на Railway для сервиса worker:
    python -m app.workers.worker_entrypoint
"""
import logging
import sys

from redis import Redis
from rq import Worker, Queue

from config import settings, looks_like_unlinked_variable

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

QUEUE_NAME = "scraper_tasks"


def main():
    if not settings.redis_url or "://" not in settings.redis_url:
        logger.error(
            "REDIS_URL некорректен или не задан (значение: %r). "
            "Проверьте переменные окружения worker-сервиса на Railway — "
            "переменную Redis-плагина нужно прилинковать отдельно к КАЖДОМУ "
            "сервису, который её использует, включая worker.",
            settings.redis_url,
        )
        sys.exit(1)

    if looks_like_unlinked_variable(settings.redis_url):
        logger.error(
            "REDIS_URL указывает на %r, но контейнер запущен на Railway "
            "(обнаружена переменная RAILWAY_ENVIRONMENT). Это значит, что "
            "переменная REDIS_URL не привязана к сервису worker — код тихо "
            "откатился на дефолт из config.py. Зайдите в Variables этого "
            "сервиса в Railway и добавьте REDIS_URL как ссылку на Redis-плагин "
            "(Add Reference -> Redis -> REDIS_URL), не вписывайте значение вручную.",
            settings.redis_url,
        )
        sys.exit(1)

    logger.info("Подключаюсь к Redis...")
    redis_conn = Redis.from_url(settings.redis_url)
    redis_conn.ping()  # быстрый явный фейл с понятной причиной, если Redis недоступен
    logger.info("Redis доступен, запускаю worker для очереди %r", QUEUE_NAME)

    queue = Queue(QUEUE_NAME, connection=redis_conn)
    worker = Worker([queue], connection=redis_conn)
    worker.work()


if __name__ == "__main__":
    main()
