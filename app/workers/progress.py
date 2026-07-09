"""
Публикация прогресса краулинга в Redis pub/sub.
WebSocket-эндпоинт (app/api/ws_routes.py) подписывается на канал и
транслирует сообщения в браузер — так dashboard видит live-прогресс.
"""
import json

import redis

from config import settings

redis_conn = redis.from_url(settings.redis_url)


def publish_progress(project_id: str, pages_done: int, pages_total: int, status: str = "running"):
    channel = f"project:{project_id}:progress"
    payload = json.dumps({
        "pages_done": pages_done,
        "pages_total": pages_total,
        "status": status,
    })
    redis_conn.publish(channel, payload)
