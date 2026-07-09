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

# "original" - без перевода; "ru"/"en" - только перевод на этот язык (заменяет колонки);
# "both" - оригинал + отдельные колонки title_ru/description_ru/title_en/description_en
LANG_CHOICES = {"original", "ru", "en", "both"}


def _base_row(item: Item) -> dict:
    return {
        "category": item.category,
        "title": item.title,
        "description": item.description,
        "subcategory": item.subcategory,
        "price": item.price,
        "image_url": item.image_url,
        "source_url": item.source_url,
        "rating": item.rating,
    }


async def _build_export_rows(db: AsyncSession, db_items: list[Item], lang: str) -> list[dict]:
    """
    Собирает все нужные к переводу тексты СРАЗУ по всему каталогу и переводит
    их одним параллельным batch-вызовом (см. translate_batch), а не по одному
    item за раз — именно последовательный перевод на больших каталогах
    упирался в gateway-таймаут Railway (502 Bad Gateway).
    """
    rows = [_base_row(i) for i in db_items]

    if lang == "original":
        return rows

    if lang in ("ru", "en"):
        all_texts = [i.title for i in db_items] + [i.description for i in db_items]
        translated_map = await translate_batch(db, all_texts, target_language=lang)
        for row, item in zip(rows, db_items):
            row["title"] = translated_map.get(item.title, item.title)
            row["description"] = translated_map.get(item.description, item.description)
        return rows

    # lang == "both": RU и EN батчи идут последовательно (каждый сам по себе уже
    # параллелит запросы к OpenAI внутри). Гнать RU и EN через asyncio.gather
    # друг с другом НЕЛЬЗЯ - оба используют одну и ту же AsyncSession, а она
    # не потокобезопасна для конкурентного использования несколькими корутинами.
    all_texts = [i.title for i in db_items] + [i.description for i in db_items]
    ru_map = await translate_batch(db, all_texts, target_language="ru")
    en_map = await translate_batch(db, all_texts, target_language="en")
    for row, item in zip(rows, db_items):
        row["title_ru"] = ru_map.get(item.title, item.title)
        row["description_ru"] = ru_map.get(item.description, item.description)
        row["title_en"] = en_map.get(item.title, item.title)
        row["description_en"] = en_map.get(item.description, item.description)
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
