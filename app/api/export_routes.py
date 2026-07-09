from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Project, Item, User
from app.security import get_current_user
from app.exports.exporter import export_to_excel, export_to_csv, export_to_json

router = APIRouter(prefix="/projects", tags=["export"])

MEDIA_TYPES = {
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "json": "application/json",
}


@router.get("/{project_id}/export/{fmt}")
async def export_items(
    project_id: str,
    fmt: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if fmt not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Формат должен быть excel, csv или json")

    project = await db.get(Project, project_id)
    if project is None or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Проект не найден")

    result = await db.execute(select(Item).where(Item.project_id == project_id))
    items = [
        {
            "title": i.title,
            "description": i.description,
            "category": i.category,
            "subcategory": i.subcategory,
            "price": i.price,
            "image_url": i.image_url,
            "source_url": i.source_url,
            "rating": i.rating,
        }
        for i in result.scalars().all()
    ]

    if fmt == "excel":
        content = export_to_excel(items)
    elif fmt == "csv":
        content = export_to_csv(items)
    else:
        content = export_to_json(items)

    filename = f"{project.name}.{'xlsx' if fmt == 'excel' else fmt}"
    return Response(
        content=content,
        media_type=MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
