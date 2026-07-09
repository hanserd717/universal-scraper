from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Project, Item, User
from app.security import get_current_user
from app.exports.exporter import export_to_excel, export_to_csv, export_to_json
from app.ai.translator import translate, LANGUAGE_NAMES

router = APIRouter(prefix="/projects", tags=["export"])

MEDIA_TYPES = {
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "json": "application/json",
}

# "original" - без перевода; "ru"/"en" - только перевод на этот язык (заменяет колонки);
# "both" - оригинал + отдельные колонки title_ru/description_ru/title_en/description_en
LANG_CHOICES = {"original", "ru", "en", "both"}


async def _translated_item(db: AsyncSession, item: Item, lang: str) -> dict:
    """
    Строит словарь для экспорта с переводом. Перевод последовательный (не параллельный) —
    AsyncSession SQLAlchemy не безопасна для конкурентных операций на одной сессии,
    а параллельные сессии на каждый item усложнили бы код непропорционально MVP-задаче.
    Для больших каталогов (тысячи items) это может занять время — учитывайте при экспорте.
    """
    base = {
        "title": item.title,
        "description": item.description,
        "category": item.category,
        "subcategory": item.subcategory,
        "price": item.price,
        "image_url": item.image_url,
        "source_url": item.source_url,
        "rating": item.rating,
    }

    if lang == "original":
        return base

    if lang in ("ru", "en"):
        base["title"] = await translate(db, item.title, target_language=lang)
        base["description"] = await translate(db, item.description, target_language=lang)
        return base

    # lang == "both": оригинал остаётся в title/description, переводы - в отдельных колонках
    base["title_ru"] = await translate(db, item.title, target_language="ru")
    base["description_ru"] = await translate(db, item.description, target_language="ru")
    base["title_en"] = await translate(db, item.title, target_language="en")
    base["description_en"] = await translate(db, item.description, target_language="en")
    return base


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

    if lang != "original":
        try:
            items = [await _translated_item(db, i, lang) for i in db_items]
        except RuntimeError as exc:
            # translator._get_client() бросает RuntimeError, если OPENAI_API_KEY не задан
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        items = [await _translated_item(db, i, "original") for i in db_items]

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
