"""
Проверка robots.txt и поиск sitemap.xml перед обходом сайта.
Включено по умолчанию (см. Project.respect_robots_txt) — уважаем правила источника.
"""
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

DEFAULT_TIMEOUT = 10


class RobotsChecker:
    """Кэширует распарсенный robots.txt на один прогон краулера (по домену)."""

    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self._cache: dict[str, RobotFileParser] = {}

    def _get_parser(self, base_url: str) -> RobotFileParser:
        parsed = urlparse(base_url)
        domain_key = f"{parsed.scheme}://{parsed.netloc}"

        if domain_key in self._cache:
            return self._cache[domain_key]

        robots_url = urljoin(domain_key, "/robots.txt")
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            resp = requests.get(robots_url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": self.user_agent})
            if resp.status_code == 200:
                parser.parse(resp.text.splitlines())
            else:
                # Нет robots.txt или недоступен -> считаем всё разрешённым
                parser.parse([])
        except requests.RequestException:
            parser.parse([])

        self._cache[domain_key] = parser
        return parser

    def is_allowed(self, url: str) -> bool:
        parser = self._get_parser(url)
        return parser.can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        parser = self._get_parser(url)
        delay = parser.crawl_delay(self.user_agent)
        return float(delay) if delay else None

    def find_sitemaps(self, base_url: str) -> list[str]:
        parser = self._get_parser(base_url)
        sitemaps = parser.site_maps()
        return sitemaps or []
