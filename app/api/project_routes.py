from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Project, Item, User, ProjectStatus
from app.schemas import ProjectCreate, ProjectOut, ItemOut
from app.security import get_current_user
from app.scraper.ssrf_guard import assert_url_is_safe, SSRFError
from app.ai.cost_guard import estimate_cost
from app.workers.queue import task_queue
from app.workers.tasks import run_crawl_job

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Критичная проверка: URL не должен указывать на внутреннюю инфраструктуру
    try:
        assert_url_is_safe(payload.url)
    except SSRFError as exc:
        raise HTTPException(status_code=400, detail=f"Недопустимый URL: {exc}")

    project = Project(
        user_id=current_user.id,
        name=payload.name,
        url=payload.url,
        data_type=payload.data_type,
        max_pages=payload.max_pages,
        depth=payload.depth,
        delay_seconds=payload.delay_seconds,
        respect_robots_txt=payload.respect_robots_txt,
        legal_confirmation=payload.legal_confirmation,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(Project).where(Project.user_id == current_user.id))
    return result.scalars().all()


async def _get_owned_project(project_id: str, db: AsyncSession, current_user: User) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return project


@router.post("/{project_id}/start")
async def start_parsing(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(project_id, db, current_user)

    if project.status == ProjectStatus.running:
        raise HTTPException(status_code=409, detail="Парсинг уже запущен")

    task_queue.enqueue(run_crawl_job, project_id, job_timeout="1h")
    return {"detail": "Парсинг запущен", "project_id": project_id}


@router.post("/{project_id}/stop")
async def stop_parsing(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(project_id, db, current_user)
    # MVP: помечаем как paused. Полная реализация graceful cancel требует
    # флага в Redis, который crawler проверяет между запросами (TODO Этап 3).
    project.status = ProjectStatus.paused
    await db.commit()
    return {"detail": "Остановлено (best-effort)"}


@router.get("/{project_id}/items", response_model=list[ItemOut])
async def list_items(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_project(project_id, db, current_user)
    result = await db.execute(select(Item).where(Item.project_id == project_id))
    return result.scalars().all()


@router.get("/{project_id}/ai-cost-estimate")
async def ai_cost_estimate(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Оценка стоимости AI-обработки ПЕРЕД запуском — показывается в UI."""
    await _get_owned_project(project_id, db, current_user)
    result = await db.execute(select(Item).where(Item.project_id == project_id))
    items_count = len(result.scalars().all())
    estimate = estimate_cost(items_count, tasks=2)  # категоризация + перевод
    return estimate
