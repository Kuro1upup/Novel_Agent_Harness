"""HTTP clients for the Go authentication and billing services."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from novel_harness.exceptions import (
    AuthenticationError,
    BillingUnavailableError,
    InsufficientBalanceError,
)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: int
    email: str = ""
    phone: str = ""
    nickname: str = ""
    avatar_url: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> AuthenticatedUser:
        try:
            user_id = int(payload["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("认证服务返回了无效的用户信息") from exc
        if user_id <= 0:
            raise AuthenticationError("认证服务返回了无效的用户 ID")
        return cls(
            id=user_id,
            email=str(payload.get("email") or ""),
            phone=str(payload.get("phone") or ""),
            nickname=str(payload.get("nickname") or ""),
            avatar_url=str(payload.get("avatar_url") or ""),
        )


class ServiceClient:
    """Small shared async client with normalized upstream failure handling."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("service base URL must not be empty")
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_seconds,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: Any = None,
        content: bytes | None = None,
        json: Any = None,
    ) -> httpx.Response:
        try:
            return await self._client.request(
                method,
                path,
                headers=headers,
                params=params,
                content=content,
                json=json,
            )
        except httpx.HTTPError as exc:
            raise ConnectionError(f"upstream request failed: {type(exc).__name__}") from exc

    async def health(self) -> bool:
        try:
            response = await self.request("GET", "/api/health")
        except ConnectionError:
            return False
        return response.status_code == 200

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class AuthServiceClient(ServiceClient):
    async def verify(self, token: str) -> AuthenticatedUser:
        if not token.strip():
            raise AuthenticationError("未提供认证信息")
        try:
            response = await self.request(
                "GET",
                "/api/auth/verify",
                headers={"Authorization": f"Bearer {token}"},
            )
        except ConnectionError as exc:
            raise AuthenticationError("认证服务暂时不可用") from exc
        if response.status_code != 200:
            raise AuthenticationError("认证已失效，请重新登录")
        try:
            payload = response.json()
        except ValueError as exc:
            raise AuthenticationError("认证服务返回了无效响应") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("user"), dict):
            raise AuthenticationError("认证服务返回了无效响应")
        return AuthenticatedUser.from_payload(payload["user"])


class BillingServiceClient(ServiceClient):
    def __init__(
        self,
        base_url: str,
        *,
        internal_api_key: str,
        timeout_seconds: float,
        required: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(base_url, timeout_seconds=timeout_seconds, client=client)
        self.internal_api_key = internal_api_key
        self.required = required

    @property
    def internal_headers(self) -> dict[str, str]:
        return {"X-Internal-Api-Key": self.internal_api_key}

    async def ensure_available_balance(self, user_id: int) -> None:
        try:
            response = await self.request(
                "GET",
                "/api/billing/internal/balance-check",
                headers=self.internal_headers,
                params={"user_id": user_id},
            )
        except ConnectionError as exc:
            if self.required:
                raise BillingUnavailableError("计费服务暂时不可用") from exc
            return
        if response.status_code != 200:
            if self.required:
                raise BillingUnavailableError("计费服务无法校验余额")
            return
        try:
            payload = response.json()
            balance = Decimal(str(payload["balance"]))
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            if self.required:
                raise BillingUnavailableError("计费服务返回了无效响应") from exc
            return
        if balance <= 0:
            raise InsufficientBalanceError("余额不足，请充值后再使用生成能力")

    async def record_usage(
        self,
        *,
        user_id: int,
        model: str,
        subsystem: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        try:
            response = await self.request(
                "POST",
                "/api/billing/internal/usage",
                headers=self.internal_headers,
                json={
                    "user_id": user_id,
                    "model": model or "unknown",
                    "subsystem": subsystem,
                    "input_tokens": max(input_tokens, 0),
                    "cache_hit_tokens": 0,
                    "cache_miss_tokens": max(input_tokens, 0),
                    "output_tokens": max(output_tokens, 0),
                },
            )
        except ConnectionError as exc:
            raise BillingUnavailableError("计费用量上报失败") from exc
        if response.status_code != 200:
            raise BillingUnavailableError(f"计费用量上报失败（HTTP {response.status_code}）")
