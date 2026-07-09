"""
Перевод через OpenAI с кэшем в БД (таблица translations), чтобы не платить
дважды за один и тот же текст. JSON-файл-кэш из ТЗ v1 заменён на БД —
файл на Railway не переживёт редеплой (эфемерная файловая система).
"""
import asyncio
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

# Сколько запросов к OpenAI держим открытыми одновременно. Ограничиваем,
# чтобы не упереться в rate limit аккаунта и не открыть слишком много
# соединений разом на большом каталоге.
MAX_CONCURRENT_TRANSLATIONS = 6


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _call_openai_sync(text: str, target_language: str) -> str:
    """Блокирующий вызов OpenAI. Всегда запускать через asyncio.to_thread."""
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
    return response.choices[0].message.content.strip()


async def translate(db: AsyncSession, text: str, target_language: str = "ru") -> str:
    """Перевод одного текста. Для многих текстов используйте translate_batch —
    он параллелит запросы и не упирается в gateway-таймаут на больших каталогах."""
    if not text:
        return text
    result = await translate_batch(db, [text], target_language)
    return result[text]


async def translate_batch(
    db: AsyncSession, texts: list[str], target_language: str
) -> dict[str, str]:
    """
    Переводит список текстов пакетно:
      1. Одним SQL-запросом проверяет кэш в БД сразу для всех текстов
         (вместо N последовательных запросов на каждый текст).
      2. Для текстов, которых нет в кэше, делает запросы к OpenAI ПАРАЛЛЕЛЬНО
         (до MAX_CONCURRENT_TRANSLATIONS одновременно), а не по одному —
         именно последовательный вариант на больших каталогах упирался
         в таймаут прокси Railway (502 Bad Gateway).
      3. Пишет новые переводы в БД одним commit в конце — без гонки за
         AsyncSession между параллельными корутинами (SQLAlchemy AsyncSession
         не потокобезопасна для конкурентного использования на одной сессии;
         тут вся конкурентность — на этапе HTTP-вызовов к OpenAI, DB-запись
         строго после того, как все результаты уже собраны).

    Возвращает {оригинальный_текст: переведённый_текст}. Пустые/None тексты
    остаются как есть.
    """
    if target_language not in LANGUAGE_NAMES:
        raise ValueError(
            f"Неподдерживаемый язык перевода: {target_language!r}. "
            f"Доступны: {list(LANGUAGE_NAMES)}"
        )

    unique_texts = {t for t in texts if t}
    if not unique_texts:
        return {t: t for t in texts}

    hash_to_text = {_hash_text(t): t for t in unique_texts}

    # Шаг 1: один запрос к кэшу вместо N
    cache_result = await db.execute(
        select(Translation).where(
            Translation.original_text_hash.in_(hash_to_text.keys()),
            Translation.language == target_language,
            Translation.model == settings.openai_model,
        )
    )
    translations: dict[str, str] = {}
    for row in cache_result.scalars().all():
        original = hash_to_text.get(row.original_text_hash)
        if original:
            translations[original] = row.translated_text

    missing = [t for t in unique_texts if t not in translations]

    # Шаг 2: параллельные запросы к OpenAI для того, чего нет в кэше
    if missing:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_TRANSLATIONS)

        async def _translate_one(text: str) -> tuple[str, str]:
            async with semaphore:
                translated = await asyncio.to_thread(_call_openai_sync, text, target_language)
                return text, translated

        results = await asyncio.gather(*(_translate_one(t) for t in missing))

        # Шаг 3: пишем всё новое в БД одним заходом (сессия используется
        # только здесь, последовательно, никакой конкурентности на ней)
        for original, translated in results:
            translations[original] = translated
            db.add(Translation(
                original_text_hash=_hash_text(original),
                original_text=original,
                translated_text=translated,
                language=target_language,
                model=settings.openai_model,
            ))
        await db.commit()

    return {t: (translations[t] if t else t) for t in texts}
