"""
AI-каталог: альтернативный способ наполнения проекта - не парсинг сайта,
а AI-подбор известных сервисов по заданным категориям. Результат сохраняется
как обычный Project/Item, поэтому дальше работает весь существующий экспорт
(Excel/CSV/JSON, с переводом RU/EN) без изменений.
"""
import re
from datetime import datetime, timezone

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


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9а-яё]+", "-", slug)
    return slug.strip("-") or "item"


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

    added_month = datetime.now(timezone.utc).strftime("%Y-%m")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        seen_source_urls = set()
        for category in payload.categories:
            services = await discover_services(category, count=payload.count_per_category)
            for service in services:
                name = (service.get("name") or "").strip()
                if not name:
                    continue

                clearnet_url = service.get("clearnet_url") or ""
                source_url = clearnet_url or f"ai-generated://{category}/{name}"
                if source_url in seen_source_urls:
                    continue  # AI мог повторить один и тот же сервис - source_url уникален в рамках проекта
                seen_source_urls.add(source_url)

                short_desc_en = service.get("short_description_en") or None

                db.add(Item(
                    project_id=project.id,
                    title=name,
                    description=short_desc_en,  # для обратной совместимости с обычным экспортом/переводом
                    category=category,
                    source_url=source_url,
                    slug=_slugify(name),
                    status_ru="Найдено AI (требует проверки)",
                    status_en="AI-suggested (needs review)",
                    added_month=added_month,
                    clearnet_url=clearnet_url or None,
                    tor_url=service.get("tor_url") or None,
                    telegram=service.get("telegram") or None,
                    short_description_en=short_desc_en,
                    full_description_en=service.get("full_description_en") or None,
                    official_website=service.get("official_website") or clearnet_url or None,
                    country=service.get("country") or None,
                    language=service.get("language") or None,
                    supported_cryptocurrencies=service.get("supported_cryptocurrencies") or None,
                    payment_methods=service.get("payment_methods") or None,
                    data_source="AI",
                    last_checked_at=today,
                ))
    except RuntimeError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    project.status = ProjectStatus.completed
    await db.commit()
    await db.refresh(project)
    return project
