"""Context-local LLM usage capture without logging prompt or manuscript bodies."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class LLMUsage:
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0


_active_usage: ContextVar[LLMUsage | None] = ContextVar("novel_harness_llm_usage", default=None)


@contextmanager
def capture_llm_usage() -> Iterator[LLMUsage]:
    usage = LLMUsage()
    token = _active_usage.set(usage)
    try:
        yield usage
    finally:
        _active_usage.reset(token)


def observe_llm_response(response: Any) -> None:
    usage = _active_usage.get()
    if usage is None:
        return
    usage.calls += 1
    usage.model = str(getattr(response, "model", "") or usage.model)
    usage.prompt_tokens += int(getattr(response, "prompt_tokens", 0) or 0)
    usage.completion_tokens += int(getattr(response, "completion_tokens", 0) or 0)


def prompt_version(agent_name: str) -> str:
    path = Path(__file__).resolve().parent / "prompts" / f"{agent_name}.md"
    if not path.is_file():
        return "none"
    return sha256(path.read_bytes()).hexdigest()[:12]
