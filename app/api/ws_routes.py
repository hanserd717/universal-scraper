"""
WebSocket-эндпоинт для live-прогресса. Подписывается на Redis pub/sub канал
project:{id}:progress (см. app/workers/progress.py) и транслирует в браузер.
"""
import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import redis.asyncio as aioredis

from config import settings

router = APIRouter()


@router.websocket("/ws/projects/{project_id}/progress")
async def project_progress_ws(websocket: WebSocket, project_id: str):
    await websocket.accept()
    redis_client = aioredis.from_url(settings.redis_url)
    pubsub = redis_client.pubsub()
    channel = f"project:{project_id}:progress"
    await pubsub.subscribe(channel)

    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
            if message and message.get("type") == "message":
                data = message["data"]
                await websocket.send_text(data.decode() if isinstance(data, bytes) else data)
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await redis_client.close()
