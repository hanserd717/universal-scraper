"""
Модели БД. Обратите внимание на UNIQUE constraints (project_id, url/source_url) —
именно они гарантируют отсутствие дублей при повторном запуске парсинга,
а не только логика приложения.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, DateTime, ForeignKey, Text,
    UniqueConstraint, Enum, Boolean, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class ProjectStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"


class DataType(str, enum.Enum):
    products = "products"
    services = "services"
    articles = "articles"
    catalogs = "catalogs"
    companies = "companies"
    jobs = "jobs"
    other = "other"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    api_quota = Column(Integer, default=10000)  # напр. лимит страниц/мес
    created_at = Column(DateTime, server_default=func.now())

    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    data_type = Column(Enum(DataType), default=DataType.other)
    status = Column(Enum(ProjectStatus), default=ProjectStatus.pending)

    max_pages = Column(Integer, default=500)
    depth = Column(Integer, default=3)
    delay_seconds = Column(Float, default=1.0)
    respect_robots_txt = Column(Boolean, default=True)
    user_agent_mode = Column(String, default="honest")  # honest | custom
    legal_confirmation = Column(Boolean, default=False)  # чекбокс "имею право собирать данные"

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    owner = relationship("User", back_populates="projects")
    pages = relationship("Page", back_populates="project", cascade="all, delete-orphan")
    items = relationship("Item", back_populates="project", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("project_id", "url", name="uq_page_project_url"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    url = Column(String, nullable=False)
    html_storage_ref = Column(String, nullable=True)  # ссылка в object storage, не сам HTML
    status = Column(String, default="pending")  # pending | fetched | error
    error_message = Column(Text, nullable=True)
    fetched_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="pages")


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("project_id", "source_url", name="uq_item_project_source_url"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=True)
    subcategory = Column(String, nullable=True)
    price = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    image_storage_ref = Column(String, nullable=True)  # путь в S3, если картинка скачана
    source_url = Column(String, nullable=False)
    rating = Column(String, nullable=True)

    content_hash = Column(String, nullable=True, index=True)  # для детекции изменений при повторном запуске

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="items")


class Translation(Base):
    __tablename__ = "translations"
    __table_args__ = (
        UniqueConstraint("original_text_hash", "language", "model", name="uq_translation_cache_key"),
    )

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    original_text_hash = Column(String, nullable=False, index=True)
    original_text = Column(Text, nullable=False)
    translated_text = Column(Text, nullable=False)
    language = Column(String, nullable=False)
    model = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
