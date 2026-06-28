"""Safe synchronous HTTP content fetcher."""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from collections.abc import Callable, Iterable
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from .base import (
    ContentFetchConfigurationError,
    ContentFetcher,
    ContentFetchSecurityError,
    ContentFetchTransportError,
    ContentTooLargeError,
    FetchResult,
    UnsupportedContentTypeError,
)

Resolver = Callable[[str, int], Iterable[str]]

_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_PLAIN_TEXT_TYPES = {"text/plain"}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
_CHARSET_RE = re.compile(r"(?:^|;)\s*charset\s*=\s*[\"']?([^;\"'\s]+)", re.IGNORECASE)
_META_CHARSET_RE = re.compile(
    rb"<meta[^>]+charset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)",
    re.IGNORECASE,
)


class HttpContentFetcher(ContentFetcher):
    """Fetch public HTML or plain text with conservative SSRF protections."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        max_retries: int = 2,
        max_response_bytes: int = 2 * 1024 * 1024,
        max_redirects: int = 5,
        user_agent: str = "novel-agent-harness/0.1",
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        if timeout <= 0:
            raise ContentFetchConfigurationError("timeout must be positive")
        if max_retries < 0:
            raise ContentFetchConfigurationError("max_retries cannot be negative")
        if max_response_bytes <= 0:
            raise ContentFetchConfigurationError("max_response_bytes must be positive")
        if max_redirects < 0:
            raise ContentFetchConfigurationError("max_redirects cannot be negative")
        if client is not None and transport is not None:
            raise ContentFetchConfigurationError("client and transport are mutually exclusive")
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_response_bytes = max_response_bytes
        self.max_redirects = max_redirects
        self.user_agent = user_agent
        self._client = client
        self._transport = transport
        self._resolver = resolver or _resolve_addresses

    def fetch(self, url: str) -> FetchResult:
        requested_url = _normalize_and_validate_url(url, self._resolver)
        client = self._client or httpx.Client(transport=self._transport)
        owns_client = self._client is None
        try:
            current_url = requested_url
            for redirect_count in range(self.max_redirects + 1):
                response_data = self._request_with_retry(client, current_url)
                status_code, headers, body = response_data
                if status_code in _REDIRECT_STATUSES:
                    location = headers.get("location")
                    if not location:
                        raise ContentFetchTransportError(
                            f"HTTP {status_code} redirect is missing a Location header"
                        )
                    if redirect_count >= self.max_redirects:
                        raise ContentFetchTransportError(
                            f"Response exceeded the {self.max_redirects} redirect limit"
                        )
                    candidate = urljoin(current_url, location)
                    current_url = _normalize_and_validate_url(candidate, self._resolver)
                    continue
                return self._build_result(
                    requested_url=requested_url,
                    final_url=current_url,
                    status_code=status_code,
                    headers=headers,
                    body=body,
                    redirect_count=redirect_count,
                )
        finally:
            if owns_client:
                client.close()
        raise ContentFetchTransportError("Request ended without a response")

    def _request_with_retry(
        self,
        client: httpx.Client,
        url: str,
    ) -> tuple[int, httpx.Headers, bytes]:
        for attempt in range(self.max_retries + 1):
            # Resolve before every attempt. This also prevents a retry from silently
            # following a DNS change to a private address.
            _normalize_and_validate_url(url, self._resolver)
            try:
                with client.stream(
                    "GET",
                    url,
                    headers={
                        "Accept": "text/html, application/xhtml+xml, text/plain;q=0.9",
                        "User-Agent": self.user_agent,
                    },
                    timeout=self.timeout,
                    follow_redirects=False,
                ) as response:
                    if response.status_code in _RETRY_STATUSES and attempt < self.max_retries:
                        self._backoff(attempt)
                        continue
                    if response.status_code >= 400:
                        raise ContentFetchTransportError(
                            f"Content server returned HTTP {response.status_code}"
                        )
                    if response.status_code in _REDIRECT_STATUSES:
                        return response.status_code, response.headers, b""
                    if 300 <= response.status_code < 400:
                        raise ContentFetchTransportError(
                            f"Unsupported HTTP redirect status {response.status_code}"
                        )
                    self._validate_content_type(response.headers)
                    self._validate_content_length(response.headers)
                    return response.status_code, response.headers, self._read_limited(response)
            except ContentFetchTransportError:
                raise
            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    raise ContentFetchTransportError(
                        f"Content request failed after {attempt + 1} attempts: {exc}"
                    ) from exc
                self._backoff(attempt)
        raise ContentFetchTransportError("Content request failed without a response")

    def _validate_content_length(self, headers: httpx.Headers) -> None:
        value = headers.get("content-length")
        if value is None:
            return
        try:
            content_length = int(value)
        except ValueError as exc:
            raise ContentFetchTransportError("Response has an invalid Content-Length") from exc
        if content_length < 0:
            raise ContentFetchTransportError("Response has an invalid Content-Length")
        if content_length > self.max_response_bytes:
            raise ContentTooLargeError(f"Response exceeds the {self.max_response_bytes}-byte limit")

    @staticmethod
    def _validate_content_type(headers: httpx.Headers) -> None:
        media_type = _media_type(headers.get("content-type", ""))
        if media_type not in _HTML_TYPES | _PLAIN_TEXT_TYPES:
            display_type = media_type or "missing Content-Type"
            raise UnsupportedContentTypeError(f"Unsupported response content type: {display_type}")

    def _read_limited(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self.max_response_bytes:
                raise ContentTooLargeError(
                    f"Response exceeds the {self.max_response_bytes}-byte limit"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _build_result(
        self,
        *,
        requested_url: str,
        final_url: str,
        status_code: int,
        headers: httpx.Headers,
        body: bytes,
        redirect_count: int,
    ) -> FetchResult:
        media_type = _media_type(headers.get("content-type", ""))
        if media_type not in _HTML_TYPES | _PLAIN_TEXT_TYPES:
            display_type = media_type or "missing Content-Type"
            raise UnsupportedContentTypeError(f"Unsupported response content type: {display_type}")
        text = _decode_body(
            body,
            headers.get("content-type", ""),
            is_html=media_type in _HTML_TYPES,
        )
        title = ""
        if media_type in _HTML_TYPES:
            parser = _ReadableHTMLParser()
            try:
                parser.feed(text)
                parser.close()
            except (UnicodeError, ValueError) as exc:
                raise ContentFetchTransportError("Response contains malformed HTML") from exc
            text = parser.readable_text
            title = parser.title
        else:
            text = _normalize_plain_text(text)
        return FetchResult(
            requested_url=requested_url,
            final_url=final_url,
            content=text,
            content_type=media_type,
            status_code=status_code,
            title=title,
            byte_count=len(body),
            metadata={"redirect_count": redirect_count},
        )

    @staticmethod
    def _backoff(attempt: int) -> None:
        time.sleep(min(0.25 * (2**attempt), 2.0))


def _normalize_and_validate_url(url: str, resolver: Resolver) -> str:
    candidate = url.strip()
    if not candidate:
        raise ContentFetchSecurityError("URL must not be empty")
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ContentFetchSecurityError("URL is malformed") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ContentFetchSecurityError("Only http and https URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise ContentFetchSecurityError("URLs containing credentials are not allowed")
    if not parsed.hostname:
        raise ContentFetchSecurityError("URL must include a hostname")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ContentFetchSecurityError("Localhost URLs are not allowed")
    effective_port = port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            addresses = tuple(resolver(hostname, effective_port))
        except (OSError, UnicodeError) as exc:
            raise ContentFetchTransportError(f"Could not resolve URL hostname: {hostname}") from exc
    else:
        addresses = (str(literal_address),)
    if not addresses:
        raise ContentFetchTransportError(f"URL hostname resolved to no addresses: {hostname}")
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ContentFetchSecurityError(
                f"Hostname resolver returned an invalid address: {address}"
            ) from exc
        if not parsed_address.is_global:
            raise ContentFetchSecurityError(
                f"URL hostname resolves to a non-public address: {address}"
            )
    netloc = parsed.netloc
    # Remove fragments because they are never sent to the server and should not
    # produce different canonical fetch targets.
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def _resolve_addresses(hostname: str, port: int) -> Iterable[str]:
    addresses: set[str] = set()
    for family, _socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(
        hostname,
        port,
        type=socket.SOCK_STREAM,
    ):
        if family in {socket.AF_INET, socket.AF_INET6}:
            addresses.add(str(sockaddr[0]))
    return addresses


def _media_type(content_type: str) -> str:
    return content_type.partition(";")[0].strip().lower()


def _decode_body(body: bytes, content_type: str, *, is_html: bool) -> str:
    charset_match = _CHARSET_RE.search(content_type)
    charset = charset_match.group(1) if charset_match else ""
    if not charset and is_html:
        meta_match = _META_CHARSET_RE.search(body[:8192])
        if meta_match:
            charset = meta_match.group(1).decode("ascii", errors="ignore")
    encoding = charset or "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _normalize_plain_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class _ReadableHTMLParser(HTMLParser):
    _SUPPRESSED = {"head", "script", "style", "nav", "noscript", "template", "svg"}
    _BLOCKS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._title_parts: list[str] = []
        self._suppressed_depth = 0
        self._in_title = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
            return
        if tag in self._SUPPRESSED:
            self._suppressed_depth += 1
            return
        if self._suppressed_depth == 0 and tag in self._BLOCKS:
            self._append_boundary()

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in {"br", "hr"}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
            return
        if tag in self._SUPPRESSED:
            if self._suppressed_depth > 0:
                self._suppressed_depth -= 1
            return
        if self._suppressed_depth == 0 and tag in self._BLOCKS:
            self._append_boundary()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._suppressed_depth == 0 and not self._in_title:
            self._parts.append(data)

    def _append_boundary(self) -> None:
        if not self._parts or self._parts[-1] != "\n":
            self._parts.append("\n")

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._title_parts)).strip()

    @property
    def readable_text(self) -> str:
        return _normalize_plain_text("".join(self._parts))
