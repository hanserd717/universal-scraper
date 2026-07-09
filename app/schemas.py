"""Pydantic-схемы для запросов/ответов API."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator

from app.models import ProjectStatus, DataType


# --- Auth ---

class UserCreate(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Пароль должен быть не короче 8 символов")
        return v


class UserOut(BaseModel):
    id: str
    email: EmailStr
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Projects ---

class ProjectCreate(BaseModel):
    name: str
    url: str
    data_type: DataType = DataType.other
    max_pages: int = 500
    depth: int = 3
    delay_seconds: float = 1.0
    respect_robots_txt: bool = True
    legal_confirmation: bool  # обязательное явное подтверждение права на сбор данных

    @field_validator("legal_confirmation")
    @classmethod
    def must_confirm(cls, v: bool) -> bool:
        if not v:
            raise ValueError(
                "Необходимо подтвердить право на сбор данных с указанного источника"
            )
        return v

    @field_validator("max_pages")
    @classmethod
    def cap_max_pages(cls, v: int) -> int:
        if v < 1 or v > 10000:
            raise ValueError("max_pages должен быть от 1 до 10000")
        return v


class ProjectOut(BaseModel):
    id: str
    name: str
    url: str
    data_type: DataType
    status: ProjectStatus
    created_at: datetime

    class Config:
        from_attributes = True


# --- Items ---

class ItemOut(BaseModel):
    id: str
    title: Optional[str]
    description: Optional[str]
    category: Optional[str]
    subcategory: Optional[str]
    price: Optional[str]
    image_url: Optional[str]
    source_url: str
    rating: Optional[str]

    class Config:
        from_attributes = True
