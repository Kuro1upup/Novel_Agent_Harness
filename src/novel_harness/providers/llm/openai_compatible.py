"""OpenAI-compatible Chat Completions provider."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from .base import (
    LLMConfigurationError,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMResponseError,
    LLMTransportError,
)


class OpenAICompatibleLLMProvider(LLMProvider):
    """Synchronous client for an OpenAI-compatible ``/chat/completions`` API."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        supports_json_schema: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url.strip():
            raise LLMConfigurationError("LLM base_url must not be empty")
        if not model.strip():
            raise LLMConfigurationError("LLM model must not be empty")
        if timeout <= 0:
            raise LLMConfigurationError("LLM timeout must be positive")
        if max_retries < 0:
            raise LLMConfigurationError("LLM max_retries cannot be negative")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.supports_json_schema = supports_json_schema
        self._client = client

    @property
    def endpoint(self) -> str:
        suffix = "/chat/completions"
        return self.base_url + suffix

    def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        response_schema: Mapping[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        if not messages:
            raise LLMConfigurationError("At least one LLM message is required")
        if not 0 <= temperature <= 2:
            raise LLMConfigurationError("temperature must be between 0 and 2")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.as_dict() for message in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            if max_tokens <= 0:
                raise LLMConfigurationError("max_tokens must be positive")
            payload["max_tokens"] = max_tokens
        if response_schema is not None:
            if self.supports_json_schema:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "structured_response",
                        "strict": True,
                        "schema": dict(response_schema),
                    },
                }
            else:
                payload["response_format"] = {"type": "json_object"}
        if extra:
            protected = {"model", "messages", "response_format"}
            collision = protected.intersection(extra)
            if collision:
                names = ", ".join(sorted(collision))
                raise LLMConfigurationError(
                    f"extra cannot override protected request fields: {names}"
                )
            payload.update(extra)

        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = self._post_with_retry(payload, headers)
        return self._normalize(data)

    def _post_with_retry(
        self, payload: Mapping[str, Any], headers: Mapping[str, str]
    ) -> Mapping[str, Any]:
        client = self._client or httpx.Client()
        owns_client = self._client is None
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    response = client.post(
                        self.endpoint,
                        json=payload,
                        headers=headers,
                        timeout=self.timeout,
                    )
                    if response.status_code in {408, 409, 429} or response.status_code >= 500:
                        if attempt < self.max_retries:
                            self._backoff(attempt, response)
                            continue
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, Mapping):
                        raise LLMResponseError("LLM response root must be a JSON object")
                    return data
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt >= self.max_retries:
                        raise LLMTransportError(
                            f"LLM request failed after {attempt + 1} attempts: {exc}"
                        ) from exc
                    time.sleep(min(0.25 * (2**attempt), 2.0))
                except httpx.HTTPStatusError as exc:
                    body = exc.response.text[:500]
                    raise LLMTransportError(
                        f"LLM returned HTTP {exc.response.status_code}: {body}"
                    ) from exc
                except ValueError as exc:
                    raise LLMResponseError("LLM returned invalid JSON") from exc
        finally:
            if owns_client:
                client.close()
        raise LLMTransportError("LLM request failed without a response")

    @staticmethod
    def _backoff(attempt: int, response: httpx.Response) -> None:
        retry_after = response.headers.get("retry-after")
        try:
            delay = min(float(retry_after), 5.0) if retry_after else 0.25 * (2**attempt)
        except ValueError:
            delay = 0.25 * (2**attempt)
        time.sleep(delay)

    def _normalize(self, data: Mapping[str, Any]) -> LLMResponse:
        try:
            choice = data["choices"][0]
            message = choice["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("LLM response is missing choices[0].message.content") from exc
        if isinstance(content, list):
            text_parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, Mapping) and item.get("type") == "text"
            ]
            content = "".join(text_parts)
        if not isinstance(content, str):
            raise LLMResponseError("LLM message content must be a string")
        usage = data.get("usage")
        usage = usage if isinstance(usage, Mapping) else {}
        return LLMResponse(
            content=content,
            model=str(data.get("model") or self.model),
            finish_reason=(
                str(choice.get("finish_reason"))
                if choice.get("finish_reason") is not None
                else None
            ),
            prompt_tokens=_optional_int(usage.get("prompt_tokens")),
            completion_tokens=_optional_int(usage.get("completion_tokens")),
            raw=data,
        )


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
