"""
AI-обработка: очистка текста и категоризация через OpenAI API.
Модель конфигурируется через config.py / ENV (OPENAI_MODEL) — можно заменить
на любую другую OpenAI-совместимую модель без изменения кода.
"""
import json
import logging

from openai import OpenAI

from config import settings

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY не задан — AI-обработка недоступна")
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


CLEAN_AND_CATEGORIZE_PROMPT = """Ты помогаешь очистить и категоризировать данные, собранные с веб-сайта.
Дан сырой текст карточки товара/услуги/компании. Верни ТОЛЬКО JSON без пояснений:
{{
  "clean_description": "краткое чистое описание без навигационного мусора (1-2 предложения)",
  "category": "основная категория",
  "subcategory": "подкатегория"
}}

Сырой текст:
Название: {title}
Описание: {description}
"""


def clean_and_categorize(title: str, description: str) -> dict:
    """
    Возвращает {"clean_description": str, "category": str, "subcategory": str}.
    Бросает исключение при ошибке API — вызывающий код (worker) должен ловить
    и помечать item как failed, не роняя весь batch.
    """
    client = _get_client()
    prompt = CLEAN_AND_CATEGORIZE_PROMPT.format(title=title or "", description=description or "")

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    content = response.choices[0].message.content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.error("AI вернул невалидный JSON: %s", content)
        return {"clean_description": description, "category": "other", "subcategory": None}
