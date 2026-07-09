"""
Перевод через OpenAI с кэшем в БД (таблица translations), чтобы не платить
дважды за один и тот же текст. JSON-файл-кэш из ТЗ v1 заменён на БД —
файл на Railway не переживёт редеплой (эфемерная файловая система).
"""
import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Translation
from config import settings
from app.ai.analyzer import _get_client

logger = logging.getLogger(__name__)

TRANSLATE_PROMPT = """Переведи следующий текст каталога товаров/услуг на {target_language_name}.
Текст может быть на любом исходном языке — определи его автоматически.
Если текст уже на {target_language_name}, верни его как есть, без изменений.

ВАЖНО — НЕ переводи:
- названия брендов и компаний
- домены и URL
- названия криптовалют
- специфические технические термины (оставляй как есть или транслитерируй)

Переводи только описания, характеристики и категории.

Верни только переведённый текст, без пояснений и кавычек.

Текст: {text}
"""

LANGUAGE_NAMES = {
    "ru": "русский язык (Russian)",
    "en": "английский язык (English)",
}


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def translate(db: AsyncSession, text: str, target_language: str = "ru") -> str:
    if not text:
        return text

    if target_language not in LANGUAGE_NAMES:
        raise ValueError(
            f"Неподдерживаемый язык перевода: {target_language!r}. "
            f"Доступны: {list(LANGUAGE_NAMES)}"
        )

    text_hash = _hash_text(text)
    result = await db.execute(
        select(Translation).where(
            Translation.original_text_hash == text_hash,
            Translation.language == target_language,
            Translation.model == settings.openai_model,
        )
    )
    cached = result.scalar_one_or_none()
    if cached:
        return cached.translated_text

    client = _get_client()
    prompt = TRANSLATE_PROMPT.format(
        target_language_name=LANGUAGE_NAMES[target_language],
        text=text,
    )
    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    translated = response.choices[0].message.content.strip()

    db.add(Translation(
        original_text_hash=text_hash,
        original_text=text,
        translated_text=translated,
        language=target_language,
        model=settings.openai_model,
    ))
    await db.commit()

    return translated
