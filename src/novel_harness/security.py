"""Request-local authenticated user context."""

from __future__ import annotations

from contextvars import ContextVar, Token

_current_user_id: ContextVar[int | None] = ContextVar(
    "novel_harness_current_user_id",
    default=None,
)


def current_user_id() -> int | None:
    """Return the authenticated user ID, or ``None`` outside an API request."""

    return _current_user_id.get()


def bind_user(user_id: int) -> Token[int | None]:
    """Bind a user ID to the current async context."""

    return _current_user_id.set(user_id)


def reset_user(token: Token[int | None]) -> None:
    """Restore the previous request-local user binding."""

    _current_user_id.reset(token)
