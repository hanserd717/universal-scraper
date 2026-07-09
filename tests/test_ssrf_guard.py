import pytest

from app.scraper.ssrf_guard import assert_url_is_safe, is_url_safe, SSRFError


def test_public_url_is_safe():
    assert is_url_safe("https://example.com") is True


def test_localhost_is_blocked():
    with pytest.raises(SSRFError):
        assert_url_is_safe("http://localhost/")


def test_loopback_ip_is_blocked():
    with pytest.raises(SSRFError):
        assert_url_is_safe("http://127.0.0.1/")


def test_cloud_metadata_ip_is_blocked():
    with pytest.raises(SSRFError):
        assert_url_is_safe("http://169.254.169.254/latest/meta-data/")


def test_private_network_is_blocked():
    with pytest.raises(SSRFError):
        assert_url_is_safe("http://10.0.0.5/")
    with pytest.raises(SSRFError):
        assert_url_is_safe("http://192.168.1.1/")


def test_non_http_scheme_is_blocked():
    with pytest.raises(SSRFError):
        assert_url_is_safe("file:///etc/passwd")
    with pytest.raises(SSRFError):
        assert_url_is_safe("ftp://example.com/")


def test_is_url_safe_does_not_raise():
    assert is_url_safe("http://127.0.0.1/") is False
