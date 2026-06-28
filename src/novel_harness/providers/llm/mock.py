"""Deterministic LLM provider for unit tests and offline development."""

from __future__ import annotations

import copy
import json
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from .base import LLMMessage, LLMProvider, LLMResponse

MockResponder = Callable[
    [Sequence[LLMMessage], Mapping[str, Any] | None],
    str | Mapping[str, Any] | LLMResponse,
]


class MockLLMProvider(LLMProvider):
    """Return queued or callback-generated deterministic completions.

    ``responses`` are consumed in order. Once exhausted, the provider returns
    ``default_response``. Mapping responses are JSON encoded, making them
    directly usable with :meth:`LLMProvider.generate_structured`.
    """

    def __init__(
        self,
        responses: Iterable[str | Mapping[str, Any] | LLMResponse] | None = None,
        *,
        responder: MockResponder | None = None,
        default_response: str | Mapping[str, Any] = "Mock LLM response",
        model: str = "mock-llm",
        auto_structured: bool = True,
    ) -> None:
        self._responses = deque(copy.deepcopy(list(responses or [])))
        self._responder = responder
        self._default_response = copy.deepcopy(default_response)
        self._auto_structured = auto_structured
        self.model = model
        self.calls: list[tuple[tuple[LLMMessage, ...], Mapping[str, Any] | None]] = []

    def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        response_schema: Mapping[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        del temperature, max_tokens, extra
        frozen_messages = tuple(messages)
        self.calls.append((frozen_messages, copy.deepcopy(response_schema)))
        if self._responder is not None:
            value = self._responder(frozen_messages, response_schema)
        elif self._responses:
            value = self._responses.popleft()
        elif response_schema is not None and self._auto_structured:
            value = _mock_from_schema(response_schema)
        else:
            value = copy.deepcopy(self._default_response)
        if isinstance(value, LLMResponse):
            return value
        content = (
            json.dumps(value, ensure_ascii=False, sort_keys=True)
            if isinstance(value, Mapping)
            else value
        )
        return LLMResponse(
            content=content,
            model=self.model,
            finish_reason="stop",
            raw={"mock": True},
        )


def _mock_from_schema(
    schema: Mapping[str, Any],
    *,
    root: Mapping[str, Any] | None = None,
) -> Any:
    """Build a minimal deterministic value from a JSON Schema."""

    root = root or schema
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/"):
        target: Any = root
        for segment in reference[2:].split("/"):
            if not isinstance(target, Mapping):
                return None
            target = target.get(segment.replace("~1", "/").replace("~0", "~"))
        if isinstance(target, Mapping):
            return _mock_from_schema(target, root=root)
    if "const" in schema:
        return copy.deepcopy(schema["const"])
    if "default" in schema:
        return copy.deepcopy(schema["default"])
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return copy.deepcopy(enum[0])
    for union_key in ("anyOf", "oneOf"):
        variants = schema.get(union_key)
        if isinstance(variants, list):
            non_null = [
                variant
                for variant in variants
                if isinstance(variant, Mapping) and variant.get("type") != "null"
            ]
            if non_null:
                return _mock_from_schema(non_null[0], root=root)
    value_type = schema.get("type")
    if value_type == "object" or isinstance(schema.get("properties"), Mapping):
        properties = schema.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
        required = schema.get("required")
        required_names = required if isinstance(required, list) else []
        result: dict[str, Any] = {}
        for name in required_names:
            property_schema = properties.get(name)
            if isinstance(name, str) and isinstance(property_schema, Mapping):
                result[name] = _mock_from_schema(property_schema, root=root)
        return result
    if value_type == "array":
        minimum = schema.get("minItems")
        count = max(int(minimum), 0) if isinstance(minimum, int) else 0
        items = schema.get("items")
        if isinstance(items, Mapping):
            return [_mock_from_schema(items, root=root) for _ in range(count)]
        return []
    if value_type == "integer":
        minimum = schema.get("minimum", schema.get("exclusiveMinimum", 0))
        return int(minimum) + (1 if "exclusiveMinimum" in schema else 0)
    if value_type == "number":
        minimum = schema.get("minimum", schema.get("exclusiveMinimum", 0.0))
        return float(minimum) + (0.1 if "exclusiveMinimum" in schema else 0.0)
    if value_type == "boolean":
        return False
    if value_type == "null":
        return None
    return "mock"
