"""
Устойчивость к блокировкам:
- честный User-Agent по умолчанию (см. правовой раздел ТЗ); ротация — только при явном custom-режиме
- per-domain rate limit (не глобальный — иначе один медленный домен душит все проекты)
- retry с экспоненциальным backoff
- circuit breaker: N ошибок подряд с одного домена -> пауза проекта
"""
import time
from collections import defaultdict
from urllib.parse import urlparse

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests

HONEST_USER_AGENT = "UniversalScraperBot/1.0 (+https://yourproject.example/bot)"

# Пул UA для custom-режима — используется только если пользователь ЯВНО включил
# user_agent_mode="custom" в настройках своего проекта (его ответственность).
CUSTOM_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]


class CircuitBreakerOpen(Exception):
    """Домен временно исключён из обхода из-за серии ошибок подряд."""
    pass


class DomainThrottle:
    """Отслеживает время последнего запроса на домен -> держит per-domain rate limit."""

    def __init__(self):
        self._last_request_at: dict[str, float] = {}
        self._consecutive_errors: dict[str, int] = defaultdict(int)
        self.max_consecutive_errors = 5

    def _domain(self, url: str) -> str:
        return urlparse(url).netloc

    def wait_if_needed(self, url: str, delay_seconds: float):
        domain = self._domain(url)
        last = self._last_request_at.get(domain)
        if last is not None:
            elapsed = time.monotonic() - last
            remaining = delay_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at[domain] = time.monotonic()

    def record_success(self, url: str):
        self._consecutive_errors[self._domain(url)] = 0

    def record_error(self, url: str):
        domain = self._domain(url)
        self._consecutive_errors[domain] += 1
        if self._consecutive_errors[domain] >= self.max_consecutive_errors:
            raise CircuitBreakerOpen(
                f"{self.max_consecutive_errors} ошибок подряд на домене {domain} — обход приостановлен"
            )


def get_user_agent(mode: str, rotation_index: int = 0) -> str:
    if mode == "custom":
        return CUSTOM_USER_AGENTS[rotation_index % len(CUSTOM_USER_AGENTS)]
    return HONEST_USER_AGENT


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(requests.RequestException),
    reraise=True,
)
def fetch_with_retry(url: str, user_agent: str, timeout: int = 15) -> requests.Response:
    """HTTP GET с таймаутом и до 3 попыток с экспоненциальным backoff."""
    resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp
