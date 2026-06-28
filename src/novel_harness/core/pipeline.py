"""Small, testable pipeline runner."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

StepCallable = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class PipelineStep:
    name: str
    handler: StepCallable


class Pipeline:
    def __init__(self, steps: Sequence[PipelineStep]) -> None:
        self.steps = tuple(steps)

    async def run(self, initial: dict[str, Any]) -> dict[str, Any]:
        state = dict(initial)
        for step in self.steps:
            result = step.handler(state)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                raise TypeError(f"pipeline step {step.name!r} must return a dict")
            state.update(result)
        return state
