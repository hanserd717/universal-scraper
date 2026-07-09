"""
Защита от SSRF (Server-Side Request Forgery).

Пользователь передаёт произвольный URL, который сервер сам же фетчит —
без проверки это позволяет атаковать внутреннюю инфраструктуру
(cloud metadata endpoints, localhost-сервисы, приватные подсети).

Использование:
    from app.scraper.ssrf_guard import assert_url_is_safe, SSRFError
    assert_url_is_safe("https://example.com")  # OK
    assert_url_is_safe("http://169.254.169.254/latest/meta-data/")  # бросит SSRFError

Проверка выполняется:
  1. на каждый исходный URL перед добавлением проекта
  2. на КАЖДЫЙ hop при следовании редиректам (redirect chain), не только на старте
"""
import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}

# Приватные / служебные диапазоны, куда краулеру нельзя ходить
BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("10.0.0.0/8"),       # private
    ipaddress.ip_network("172.16.0.0/12"),    # private
    ipaddress.ip_network("192.168.0.0/16"),   # private
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud metadata (AWS/GCP/Azure)
    ipaddress.ip_network("100.64.0.0/10"),    # carrier-grade NAT
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
]

BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


class SSRFError(ValueError):
    """Бросается, когда URL указывает на запрещённый внутренний адрес."""
    pass


def _is_ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # не распарсился как IP — считаем небезопасным по умолчанию
    return any(ip in net for net in BLOCKED_NETWORKS)


def assert_url_is_safe(url: str) -> None:
    """
    Бросает SSRFError, если URL нельзя безопасно фетчить.
    Вызывать перед КАЖДЫМ HTTP-запросом краулера, включая переходы по редиректам.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SSRFError(f"Запрещённая схема URL: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("URL без хоста")

    if hostname.lower() in BLOCKED_HOSTNAMES:
        raise SSRFError(f"Запрещённый хост: {hostname}")

    # Резолвим DNS и проверяем ВСЕ полученные адреса (защита от DNS rebinding)
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SSRFError(f"Не удалось резолвить хост {hostname}: {exc}") from exc

    resolved_ips = {info[4][0] for info in addr_infos}
    if not resolved_ips:
        raise SSRFError(f"Хост {hostname} не резолвится ни в один IP")

    for ip in resolved_ips:
        if _is_ip_blocked(ip):
            raise SSRFError(
                f"Хост {hostname} резолвится в запрещённый внутренний адрес {ip}"
            )


def is_url_safe(url: str) -> bool:
    """Безопасная (не бросающая исключение) обёртка над assert_url_is_safe."""
    try:
        assert_url_is_safe(url)
        return True
    except SSRFError:
        return False
