"""
Клиент для S3-совместимого object storage (Cloudflare R2 / Backblaze B2 / AWS S3).
Нужен, потому что Railway-контейнеры эфемерны — локально сохранённые
картинки пропадут при следующем деплое/рестарте.
"""
import hashlib
import logging

import boto3
import requests

from config import settings

logger = logging.getLogger(__name__)

_s3 = None


def _get_client():
    global _s3
    if _s3 is None:
        if not settings.s3_endpoint:
            raise RuntimeError("S3_ENDPOINT не задан — object storage не настроен")
        _s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
    return _s3


def download_and_store_image(image_url: str, timeout: int = 15) -> str | None:
    """
    Скачивает картинку по URL и кладёт в bucket. Возвращает storage key
    (для сохранения в Item.image_storage_ref) или None при ошибке.
    """
    try:
        resp = requests.get(image_url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Не удалось скачать изображение %s: %s", image_url, exc)
        return None

    key = f"images/{hashlib.sha256(image_url.encode()).hexdigest()}.jpg"
    try:
        client = _get_client()
        client.put_object(Bucket=settings.s3_bucket, Key=key, Body=resp.content)
        return key
    except Exception:
        logger.exception("Не удалось загрузить изображение в S3: %s", image_url)
        return None
