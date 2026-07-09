"""Настройка RQ (Redis Queue) — проще Celery для MVP на Railway."""
import redis
from rq import Queue

from config import settings

redis_conn = redis.from_url(settings.redis_url)
task_queue = Queue("scraper_tasks", connection=redis_conn)
