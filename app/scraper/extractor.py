"""
Универсальный экстрактор данных из HTML.

MVP-подход: эвристики на основе распространённых паттернов разметки
(schema.org microdata/JSON-LD, og:-теги, типичные CSS-классы цены/названия).
Там, где эвристики не справляются — можно передать HTML в app/ai/analyzer.py
для AI-экстракции (дороже, но точнее на нестандартной вёрстке).
"""
import hashlib
import json
import re
from dataclasses import dataclass, asdict
from typing import Optional

from bs4 import BeautifulSoup

PRICE_PATTERN = re.compile(r"[\$€£₽]\s?\d[\d\s.,]*|\d[\d\s.,]*\s?(?:USD|EUR|RUB|руб|₽)", re.IGNORECASE)


@dataclass
class ExtractedItem:
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[str] = None
    image_url: Optional[str] = None
    rating: Optional[str] = None
    category: Optional[str] = None

    def content_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_json_ld(soup: BeautifulSoup) -> Optional[dict]:
    """Пытается найти structured data (schema.org Product/Article/etc) в JSON-LD."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, list):
            data = next((d for d in data if isinstance(d, dict)), None)
        if isinstance(data, dict) and "@type" in data:
            return data
    return None


def _og_tag(soup: BeautifulSoup, prop: str) -> Optional[str]:
    tag = soup.find("meta", property=f"og:{prop}")
    return tag["content"].strip() if tag and tag.get("content") else None


def extract_item(html: str, url: str) -> ExtractedItem:
    """
    Извлекает данные карточки из HTML одной страницы.
    Порядок приоритета: JSON-LD structured data -> og:-теги -> эвристика по тексту.
    """
    soup = BeautifulSoup(html, "lxml")

    json_ld = _extract_json_ld(soup)
    if json_ld:
        offers = json_ld.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        return ExtractedItem(
            title=json_ld.get("name"),
            description=json_ld.get("description"),
            price=str(offers.get("price")) if offers.get("price") else None,
            image_url=json_ld.get("image") if isinstance(json_ld.get("image"), str) else None,
            rating=str(json_ld.get("aggregateRating", {}).get("ratingValue"))
            if isinstance(json_ld.get("aggregateRating"), dict) else None,
        )

    title = _og_tag(soup, "title") or (soup.title.string.strip() if soup.title and soup.title.string else None)
    description = _og_tag(soup, "description")
    if not description:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        description = meta_desc["content"].strip() if meta_desc and meta_desc.get("content") else None
    image_url = _og_tag(soup, "image")

    price = None
    price_match = PRICE_PATTERN.search(soup.get_text(" "))
    if price_match:
        price = price_match.group(0).strip()

    return ExtractedItem(
        title=title,
        description=description,
        price=price,
        image_url=image_url,
    )


def clean_text(raw: str) -> str:
    """
    Простая очистка "мусорного" текста (навигационные ярлыки, CTA-фразы).
    Для более качественной очистки — см. app/ai/analyzer.py (AI-версия).
    """
    junk_phrases = {"home", "click here", "read more", "learn more", "sign up", "menu"}
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    cleaned = [ln for ln in lines if ln.lower() not in junk_phrases]
    return " ".join(cleaned)
