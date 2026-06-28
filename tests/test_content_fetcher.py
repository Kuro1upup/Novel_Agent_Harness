from __future__ import annotations

import httpx
import pytest

from novel_harness.providers.content import (
    ContentFetchSecurityError,
    ContentFetchTransportError,
    ContentTooLargeError,
    HttpContentFetcher,
    UnsupportedContentTypeError,
)

PUBLIC_IP = "93.184.216.34"


def _public_resolver(hostname: str, port: int) -> list[str]:
    assert hostname
    assert port > 0
    return [PUBLIC_IP]


def test_fetches_and_cleans_html_with_injected_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == "novel-agent-harness/0.1"
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=(
                b"<html><head><title>Useful page</title><style>bad</style></head>"
                b"<body><nav>menu</nav><main><h1>Heading</h1>"
                b"<p>Visible &amp; useful.</p><script>steal()</script></main></body></html>"
            ),
        )

    fetcher = HttpContentFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_public_resolver,
    )
    result = fetcher.fetch("https://example.com/article#section")

    assert result.requested_url == "https://example.com/article"
    assert result.final_url == "https://example.com/article"
    assert result.title == "Useful page"
    assert result.content == "Heading\nVisible & useful."
    assert result.content_type == "text/html"
    assert result.byte_count > 0
    assert "menu" not in result.content
    assert "steal" not in result.content


def test_fetches_plain_text() -> None:
    fetcher = HttpContentFetcher(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/plain; charset=utf-8"},
                content="第一段\r\n\r\n第二段".encode(),
            )
        ),
        resolver=_public_resolver,
    )

    result = fetcher.fetch("http://example.com/source.txt")

    assert result.text == "第一段\n\n第二段"
    assert result.url == "http://example.com/source.txt"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/a",
        "http://localhost/a",
        "http://user:password@example.com/a",
    ],
)
def test_rejects_unsafe_url_shapes(url: str) -> None:
    fetcher = HttpContentFetcher(
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        resolver=_public_resolver,
    )

    with pytest.raises(ContentFetchSecurityError):
        fetcher.fetch(url)


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "192.0.2.1"],
)
def test_rejects_non_public_resolved_addresses(address: str) -> None:
    fetcher = HttpContentFetcher(
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        resolver=lambda hostname, port: [address],
    )

    with pytest.raises(ContentFetchSecurityError):
        fetcher.fetch("http://public-name.example/resource")


def test_validates_redirect_target_before_second_request() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    fetcher = HttpContentFetcher(
        transport=httpx.MockTransport(handler),
        resolver=_public_resolver,
    )

    with pytest.raises(ContentFetchSecurityError):
        fetcher.fetch("https://example.com/start")
    assert requests == 1


def test_rejects_unsupported_content_type() -> None:
    fetcher = HttpContentFetcher(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=b"%PDF",
            )
        ),
        resolver=_public_resolver,
    )

    with pytest.raises(UnsupportedContentTypeError):
        fetcher.fetch("https://example.com/file")


def test_enforces_streamed_response_size_limit() -> None:
    fetcher = HttpContentFetcher(
        max_response_bytes=4,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"12345",
            )
        ),
        resolver=_public_resolver,
    )

    with pytest.raises(ContentTooLargeError):
        fetcher.fetch("https://example.com/large")


def test_retries_transient_transport_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("temporary failure", request=request)
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"ok",
        )

    fetcher = HttpContentFetcher(
        max_retries=1,
        transport=httpx.MockTransport(handler),
        resolver=_public_resolver,
    )

    assert fetcher.fetch("https://example.com").content == "ok"
    assert attempts == 2


def test_reports_http_errors_without_exposing_response_body() -> None:
    fetcher = HttpContentFetcher(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, content=b"secret response")
        ),
        resolver=_public_resolver,
    )

    with pytest.raises(ContentFetchTransportError, match="HTTP 403") as error:
        fetcher.fetch("https://example.com/private")
    assert "secret response" not in str(error.value)
