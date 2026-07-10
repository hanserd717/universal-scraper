from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Project, Item, User
from app.security import get_current_user
from app.exports.exporter import export_to_excel, export_to_csv, export_to_json
from app.ai.translator import translate_batch

router = APIRouter(prefix="/projects", tags=["export"])

MEDIA_TYPES = {
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "json": "application/json",
}

# "original" - без AI-перевода, что записано, то и выводим (в т.ч. пустые ячейки,
# если данных нет - см. заполнение через AI-каталог, app/api/catalog_routes.py);
# "ru"/"en"/"both" - дополнительно ПРОСИТ AI перевести короткое описание на
# недостающий язык там, где есть только один вариант (например, при обычном
# парсинге сайта, где своего RU/EN разделения нет).
LANG_CHOICES = {"original", "ru", "en", "both"}

# Точный порядок и русские заголовки колонок под шаблон каталога.
# Второй элемент кортежа - функция получения значения из Item.
TEMPLATE_COLUMNS = [
    ("Название", lambda i: i.title),
    ("Slug", lambda i: i.slug),
    ("Тег", lambda i: i.tag),
    ("Статус RU", lambda i: i.status_ru),
    ("Статус EN", lambda i: i.status_en),
    ("Добавлен (YYYY-MM)", lambda i: i.added_month),
    ("Категория", lambda i: i.category),
    ("Подкатегория", lambda i: i.subcategory),
    ("Clearnet URL", lambda i: i.clearnet_url or i.source_url),
    ("Tor URL (.onion)", lambda i: i.tor_url),
    ("App Store URL", lambda i: i.app_store_url),
    ("Google Play URL", lambda i: i.google_play_url),
    ("Telegram", lambda i: i.telegram),
    ("Краткое описание RU", lambda i: i.short_description_ru),
    ("Краткое описание EN", lambda i: i.short_description_en or i.description),
    ("Полное описание RU", lambda i: i.full_description_ru),
    ("Полное описание EN", lambda i: i.full_description_en),
    ("Возможности (RU/EN)", lambda i: i.features),
    ("Официальный сайт", lambda i: i.official_website or i.clearnet_url or i.source_url),
    ("Логотип (URL)", lambda i: i.logo_url or i.image_url),
    ("Скриншот (URL)", lambda i: i.screenshot_url),
    ("Страна", lambda i: i.country),
    ("Язык", lambda i: i.language),
    ("Валюты", lambda i: i.currencies),
    ("Способы оплаты", lambda i: i.payment_methods),
    ("Поддерживаемые криптовалюты", lambda i: i.supported_cryptocurrencies),
    ("Email", lambda i: i.email),
    ("Социальные сети", lambda i: i.social_media),
    ("Рейтинг", lambda i: i.rating),
    ("Количество отзывов", lambda i: i.review_count),
    ("Источник", lambda i: i.data_source),
    ("Дата последней проверки", lambda i: i.last_checked_at),
    ("Дата добавления", lambda i: i.created_at.strftime("%Y-%m-%d") if i.created_at else None),
    ("Примечания", lambda i: i.notes),
]


def _row_from_item(item: Item, row_id: int) -> dict:
    row = {"ID": row_id}
    for header, getter in TEMPLATE_COLUMNS:
        row[header] = getter(item)
    return row


async def _fill_missing_translations(db: AsyncSession, db_items: list[Item], rows: list[dict], lang: str):
    """
    Точечно дозаполняет 'Краткое описание RU'/'Краткое описание EN' там, где
    один из вариантов есть, а другого нет (типичный случай для items,
    собранных обычным парсингом сайта - там нет готового RU/EN разделения).
    Не трогает остальные поля шаблона - их либо знает AI-каталог, либо они
    остаются пустыми, как и предупреждали в UI.
    """
    if lang not in ("ru", "en", "both"):
        return

    need_ru = lang in ("ru", "both")
    need_en = lang in ("en", "both")

    if need_ru:
        missing_ru_sources = [
            row["Краткое описание EN"]
            for row in rows
            if not row["Краткое описание RU"] and row["Краткое описание EN"]
        ]
        if missing_ru_sources:
            ru_map = await translate_batch(db, missing_ru_sources, target_language="ru")
            for row in rows:
                if not row["Краткое описание RU"] and row["Краткое описание EN"]:
                    row["Краткое описание RU"] = ru_map.get(row["Краткое описание EN"])

    if need_en:
        missing_en_sources = [
            row["Краткое описание RU"]
            for row in rows
            if not row["Краткое описание EN"] and row["Краткое описание RU"]
        ]
        if missing_en_sources:
            en_map = await translate_batch(db, missing_en_sources, target_language="en")
            for row in rows:
                if not row["Краткое описание EN"] and row["Краткое описание RU"]:
                    row["Краткое описание EN"] = en_map.get(row["Краткое описание RU"])


async def _build_export_rows(db: AsyncSession, db_items: list[Item], lang: str) -> list[dict]:
    rows = [_row_from_item(item, idx) for idx, item in enumerate(db_items, start=1)]
    await _fill_missing_translations(db, db_items, rows, lang)
    return rows


@router.get("/{project_id}/export/{fmt}")
async def export_items(
    project_id: str,
    fmt: str,
    lang: str = Query("original", description="original | ru | en | both"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if fmt not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Формат должен быть excel, csv или json")

    if lang not in LANG_CHOICES:
        raise HTTPException(
            status_code=400,
            detail=f"lang должен быть одним из {sorted(LANG_CHOICES)}",
        )

    project = await db.get(Project, project_id)
    if project is None or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Проект не найден")

    result = await db.execute(select(Item).where(Item.project_id == project_id))
    db_items = result.scalars().all()

    try:
        items = await _build_export_rows(db, db_items, lang)
    except RuntimeError as exc:
        # translator._get_client() бросает RuntimeError, если OPENAI_API_KEY не задан
        raise HTTPException(status_code=400, detail=str(exc))

    if fmt == "excel":
        content = export_to_excel(items)
    elif fmt == "csv":
        content = export_to_csv(items)
    else:
        content = export_to_json(items)

    lang_suffix = "" if lang == "original" else f"_{lang}"
    filename = f"{project.name}{lang_suffix}.{'xlsx' if fmt == 'excel' else fmt}"
    return Response(
        content=content,
        media_type=MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
