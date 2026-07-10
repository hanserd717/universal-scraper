"""
AI-подбор известных сервисов по категориям (без реального веб-поиска —
модель отвечает на основе обучающих данных, не "гуглит" в реальном времени).
Используется как альтернативный способ наполнения каталога вместо парсинга
конкретного сайта: пользователь даёт список категорий, AI предлагает
известные реальные проекты по каждой.

Важно: результат может быть неполным, немного устаревшим или содержать
неточности в деталях (URL, статус) — модель явно проинструктирована не
выдумывать несуществующие сервисы и помечать неуверенные пункты, но
100% точность не гарантирована. Рекомендуем проверять вручную перед публикацией.
"""
import json
import logging

from config import settings
from app.ai.analyzer import _get_client

logger = logging.getLogger(__name__)

DISCOVER_PROMPT = """Ты помогаешь составить каталог реальных, хорошо известных сервисов/проектов в категории "{category}".

Перечисли до {count} РЕАЛЬНО СУЩЕСТВУЮЩИХ, хорошо известных проектов в этой категории.

СТРОГИЕ ПРАВИЛА:
- Только реальные проекты, которые ты действительно знаешь — НЕ выдумывай названия и не додумывай детали.
- Если уверенных примеров меньше, чем {count} — верни столько, сколько знаешь точно, не добивай список выдумками.
- Не включай нелегальные, мошеннические сервисы или сервисы для обхода закона.
- Для КАЖДОГО поля: если не уверен в точном значении — оставь пустую строку "". Лучше пустое поле, чем неверная информация.
- Поле tor_url заполняй, только если ТОЧНО знаешь официальный .onion-адрес проекта — в подавляющем большинстве случаев оставляй пустым.

Верни ТОЛЬКО JSON-массив, без пояснений, без ```markdown, в формате:
[
  {{
    "name": "Название",
    "short_description_en": "Краткое описание на английском, 1 предложение",
    "full_description_en": "Более подробное описание на английском, 2-4 предложения",
    "clearnet_url": "https://... или пустая строка",
    "official_website": "https://... (обычно совпадает с clearnet_url) или пустая строка",
    "tor_url": "",
    "telegram": "@username или пустая строка",
    "country": "страна происхождения или пустая строка",
    "language": "основной язык интерфейса или пустая строка",
    "supported_cryptocurrencies": "через запятую, если применимо к категории, иначе пустая строка",
    "payment_methods": "через запятую, если известно, иначе пустая строка"
  }}
]
"""


async def discover_services(category: str, count: int = 5) -> list[dict]:
    """
    Возвращает список {"name", "description", "url"} для категории.
    Бросает RuntimeError, если OPENAI_API_KEY не настроен (как и остальные AI-функции).
    """
    client = _get_client()
    prompt = DISCOVER_PROMPT.format(category=category, count=count)

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    content = response.choices[0].message.content.strip()

    # Модель иногда оборачивает JSON-массив в ```json ... ``` несмотря на инструкцию —
    # аккуратно вырезаем, если так произошло.
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].strip()

    try:
        data = json.loads(content)
        if isinstance(data, dict):
            # На случай, если модель обернула массив в {"services": [...]}
            data = next((v for v in data.values() if isinstance(v, list)), [])
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        logger.error("AI вернул невалидный JSON для категории %r: %s", category, content)
        return []
