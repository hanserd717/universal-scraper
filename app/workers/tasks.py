"""
Фоновая задача краулинга. Ставится в очередь через app/workers/queue.py,
исполняется отдельным RQ worker-процессом (см. Dockerfile / Procfile).
"""
import logging

from app.workers.db_sync import SyncSessionLocal
from app.workers.progress import publish_progress
from app.scraper.crawler import crawl
from app.models import Project, Page, Item, ProjectStatus

logger = logging.getLogger(__name__)


def run_crawl_job(project_id: str):
    """
    Точка входа для RQ: task_queue.enqueue(run_crawl_job, project_id).

    Идемпотентность: используем UNIQUE(project_id, source_url) на items и
    UNIQUE(project_id, url) на pages — повторный запуск не создаёт дублей,
    существующие записи обновляются (upsert-подобная логика через merge).
    """
    session = SyncSessionLocal()
    try:
        project = session.get(Project, project_id)
        if project is None:
            logger.error("Проект %s не найден", project_id)
            return

        project.status = ProjectStatus.running
        session.commit()

        def on_progress(done: int, total: int):
            publish_progress(project_id, done, total, status="running")

        result = crawl(
            start_url=project.url,
            max_pages=project.max_pages,
            max_depth=project.depth,
            delay_seconds=project.delay_seconds,
            respect_robots=project.respect_robots_txt,
            user_agent_mode=project.user_agent_mode,
            progress_callback=on_progress,
        )

        for url in result.pages_visited:
            existing = session.query(Page).filter_by(project_id=project_id, url=url).first()
            if existing is None:
                session.add(Page(project_id=project_id, url=url, status="fetched"))

        for source_url, extracted in result.items:
            content_hash = extracted.content_hash()
            existing_item = session.query(Item).filter_by(
                project_id=project_id, source_url=source_url
            ).first()

            if existing_item and existing_item.content_hash == content_hash:
                continue  # ничего не изменилось — пропускаем, не плодим дубли/лишние updated_at

            if existing_item:
                existing_item.title = extracted.title
                existing_item.description = extracted.description
                existing_item.price = extracted.price
                existing_item.image_url = extracted.image_url
                existing_item.rating = extracted.rating
                existing_item.content_hash = content_hash
            else:
                session.add(Item(
                    project_id=project_id,
                    source_url=source_url,
                    title=extracted.title,
                    description=extracted.description,
                    price=extracted.price,
                    image_url=extracted.image_url,
                    rating=extracted.rating,
                    content_hash=content_hash,
                ))

        project.status = ProjectStatus.completed
        session.commit()
        publish_progress(project_id, len(result.pages_visited), project.max_pages, status="completed")

    except Exception:
        logger.exception("Задача краулинга упала для проекта %s", project_id)
        project = session.get(Project, project_id)
        if project:
            project.status = ProjectStatus.failed
            session.commit()
        publish_progress(project_id, 0, 0, status="failed")
        raise
    finally:
        session.close()
