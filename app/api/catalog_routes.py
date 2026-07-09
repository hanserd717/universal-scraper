"""
AI-каталог: альтернативный способ наполнения проекта - не парсинг сайта,
а AI-подбор известных сервисов по заданным категориям. Результат сохраняется
как обычный Project/Item, поэтому дальше работает весь существующий экспорт
(Excel/CSV/JSON, с переводом RU/EN) без изменений.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Project, Item, User, ProjectStatus, DataType
from app.security import get_current_user
from app.ai.catalog_discovery import discover_services
from app.schemas import ProjectOut

router = APIRouter(prefix="/catalog", tags=["catalog"])


class CatalogDiscoverRequest(BaseModel):
    name: str
    categories: list[str]
    count_per_category: int = 5

    @field_validator("categories")
    @classmethod
    def non_empty_categories(cls, v: list[str]) -> list[str]:
        cleaned = [c.strip() for c in v if c.strip()]
        if not cleaned:
            raise ValueError("Нужна хотя бы одна категория")
        if len(cleaned) > 20:
            raise ValueError("Не более 20 категорий за раз")
        return cleaned

    @field_validator("count_per_category")
    @classmethod
    def sane_count(cls, v: int) -> int:
        if v < 1 or v > 20:
            raise ValueError("count_per_category должен быть от 1 до 20")
        return v


@router.post("/discover", response_model=ProjectOut)
async def discover_catalog(
    payload: CatalogDiscoverRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Создаёт новый проект и наполняет его AI-подобранными сервисами по каждой
    категории. Синхронно (без очереди) - категорий немного, каждая - один
    запрос к OpenAI, укладывается в обычный таймаут HTTP-запроса.
    """
    project = Project(
        user_id=current_user.id,
        name=payload.name,
        url="ai-generated://catalog",  # не настоящий URL - этот проект не парсит сайт
        data_type=DataType.catalogs,
        status=ProjectStatus.running,
        legal_confirmation=True,  # AI-генерация, не сбор данных с конкретного источника
    )
    db.add(project)
    await db.flush()  # получаем project.id, не коммитим ещё

    try:
        seen_source_urls = set()
        for category in payload.categories:
            services = await discover_services(category, count=payload.count_per_category)
            for service in services:
                name = (service.get("name") or "").strip()
                if not name:
                    continue
                source_url = service.get("url") or f"ai-generated://{category}/{name}"
                if source_url in seen_source_urls:
                    continue  # AI мог повторить один и тот же сервис - source_url уникален в рамках проекта
                seen_source_urls.add(source_url)
                db.add(Item(
                    project_id=project.id,
                    title=name,
                    description=service.get("description") or None,
                    category=category,
                    source_url=source_url,
                ))
    except RuntimeError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    project.status = ProjectStatus.completed
    await db.commit()
    await db.refresh(project)
    return project
