"""Explicit task-to-agent routing."""

from __future__ import annotations

from typing import Any


class TaskRouter:
    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        self._routes = dict(routes or {})

    def register(self, task: str, agent: Any) -> None:
        if not task:
            raise ValueError("task name cannot be empty")
        self._routes[task] = agent

    def resolve(self, task: str) -> Any:
        try:
            return self._routes[task]
        except KeyError as exc:
            raise KeyError(f"no agent registered for task {task!r}") from exc
