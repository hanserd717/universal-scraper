"""
Универсальный краулер. Обходит сайт с уважением к robots.txt,
per-domain rate limit, SSRF-защитой на каждый переход и circuit breaker.
"""
import logging
from collections import deque
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.scraper.ssrf_guard import assert_url_is_safe, SSRFError
from app.scraper.robots import RobotsChecker
from app.scraper.antiblock import DomainThrottle, CircuitBreakerOpen, fetch_with_retry, get_user_agent
from app.scraper.extractor import extract_item, ExtractedItem

logger = logging.getLogger(__name__)


class CrawlResult:
    def __init__(self):
        self.pages_visited: list[str] = []
        self.pages_failed: dict[str, str] = {}
        self.items: list[tuple[str, ExtractedItem]] = []  # (source_url, item)


def crawl(
    start_url: str,
    max_pages: int = 500,
    max_depth: int = 3,
    delay_seconds: float = 1.0,
    respect_robots: bool = True,
    user_agent_mode: str = "honest",
    same_domain_only: bool = True,
    progress_callback=None,
) -> CrawlResult:
    """
    Синхронный BFS-обход сайта. Для больших объёмов запускать внутри RQ worker
    (см. app/workers/tasks.py), не в основном web-процессе.

    progress_callback(pages_done: int, pages_total_estimate: int) — опционально,
    для публикации live-прогресса в Redis (см. app/workers/progress.py).
    """
    assert_url_is_safe(start_url)  # проверка исходного URL

    user_agent = get_user_agent(user_agent_mode)
    robots = RobotsChecker(user_agent)
    throttle = DomainThrottle()
    start_domain = urlparse(start_url).netloc

    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    result = CrawlResult()

    while queue and len(result.pages_visited) < max_pages:
        url, depth = queue.popleft()

        if url in visited or depth > max_depth:
            continue
        visited.add(url)

        # SSRF-проверка на КАЖДЫЙ URL, не только на старте (защита от вредоносных ссылок на странице)
        try:
            assert_url_is_safe(url)
        except SSRFError as exc:
            logger.warning("Пропущен небезопасный URL %s: %s", url, exc)
            result.pages_failed[url] = str(exc)
            continue

        if respect_robots and not robots.is_allowed(url):
            logger.info("robots.txt запрещает обход %s", url)
            continue

        effective_delay = robots.crawl_delay(url) or delay_seconds
        throttle.wait_if_needed(url, effective_delay)

        try:
            resp = fetch_with_retry(url, user_agent)
        except Exception as exc:  # noqa: BLE001 — логируем и продолжаем обход
            logger.warning("Ошибка запроса %s: %s", url, exc)
            result.pages_failed[url] = str(exc)
            try:
                throttle.record_error(url)
            except CircuitBreakerOpen as breaker_exc:
                logger.error(str(breaker_exc))
                break
            continue

        throttle.record_success(url)
        result.pages_visited.append(url)

        item = extract_item(resp.text, url)
        result.items.append((url, item))

        if progress_callback:
            progress_callback(len(result.pages_visited), max_pages)

        # Собираем ссылки для дальнейшего обхода
        if depth < max_depth:
            soup = BeautifulSoup(resp.text, "lxml")
            for link in soup.find_all("a", href=True):
                next_url = urljoin(url, link["href"])
                next_domain = urlparse(next_url).netloc
                if same_domain_only and next_domain != start_domain:
                    continue
                if next_url not in visited:
                    queue.append((next_url, depth + 1))

    return result
