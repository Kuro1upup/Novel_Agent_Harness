"""Provider-neutral synchronous LLM contracts."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar, overload

from pydantic import BaseModel, ValidationError

from novel_harness.exceptions import ProviderError
from novel_harness.observability import observe_llm_response

ResponseT = TypeVar("ResponseT", bound=BaseModel)
MessageRole = Literal["system", "user", "assistant", "tool"]


class LLMError(ProviderError):
    """Base error raised by an LLM provider."""


class LLMConfigurationError(LLMError):
    """The provider configuration is incomplete or invalid."""


class LLMTransportError(LLMError):
    """The remote LLM could not be reached or rejected the request."""


class LLMResponseError(LLMError):
    """The provider returned a malformed or schema-invalid response."""


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """A provider-neutral chat message."""

    role: MessageRole
    content: str
    name: str | None = None

    def as_dict(self) -> dict[str, str]:
        result = {"role": self.role, "content": self.content}
        if self.name:
            result["name"] = self.name
        return result


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Normalized result from a chat completion."""

    content: str
    model: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


class LLMProvider(ABC, Generic[ResponseT]):
    """Synchronous language-model interface.

    Implementations only need to implement :meth:`complete`. The convenience
    methods centralize prompt construction and Pydantic validation so every
    provider has identical structured-output behavior.
    """

    @abstractmethod
    def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        response_schema: Mapping[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        """Return a normalized completion for ``messages``."""

    @overload
    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        response_model: None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> str: ...

    @overload
    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        response_model: type[ResponseT],
        temperature: float = 0.2,
        max_tokens: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> ResponseT: ...

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        response_model: type[ResponseT] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> str | ResponseT:
        """Generate text or a validated Pydantic model."""

        messages: list[LLMMessage] = []
        if system_prompt:
            messages.append(LLMMessage(role="system", content=system_prompt))
        messages.append(LLMMessage(role="user", content=prompt))
        schema = response_model.model_json_schema() if response_model else None
        response = self.complete(
            messages,
            response_schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            extra=extra,
        )
        observe_llm_response(response)
        if response_model is None:
            return response.content
        return self.parse_structured(response.content, response_model)

    def generate_structured(
        self,
        prompt: str,
        response_model: type[ResponseT] | None = None,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> ResponseT | str:
        """Generate validated output, or text when a dispatcher supplies no model."""

        return self.generate(
            prompt,
            system_prompt=system_prompt,
            response_model=response_model,
            temperature=temperature,
            max_tokens=max_tokens,
            extra=extra,
        )

    @staticmethod
    def parse_structured(content: str, response_model: type[ResponseT]) -> ResponseT:
        """Parse JSON, accepting a single fenced JSON block."""

        candidate = content.strip()
        if candidate.startswith("```"):
            first_newline = candidate.find("\n")
            last_fence = candidate.rfind("```")
            if first_newline >= 0 and last_fence > first_newline:
                candidate = candidate[first_newline + 1 : last_fence].strip()
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise LLMResponseError(
                f"LLM response is not valid JSON: {exc.msg} at character {exc.pos}"
            ) from exc
        try:
            # JSON-object-only providers may add harmless bookkeeping fields
            # even when the prompt contains a schema. Strip those fields at the
            # provider boundary; the resulting domain model remains strict.
            return response_model.model_validate(payload, extra="ignore")
        except ValidationError as exc:
            raise LLMResponseError(
                f"LLM response does not match {response_model.__name__}: {exc}"
            ) from exc
