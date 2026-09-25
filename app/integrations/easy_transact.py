"""Easy Transact HTTP adapter with no simulated payment fallback."""

from dataclasses import dataclass
from decimal import Decimal
import os
from typing import Any, Mapping

import httpx

from app.core.config import settings


class EasyTransactError(RuntimeError):
    pass


@dataclass(frozen=True)
class EasyTransactClient:
    base_url: str
    api_token: str
    timeout_seconds: float = 10.0

    @classmethod
    def from_settings(cls, api_token: str | None = None) -> "EasyTransactClient":
        token = api_token or settings.EASYTRANSACT_API_TOKEN
        if not settings.EASYTRANSACT_API_BASE_URL or not token:
            raise EasyTransactError("Easy Transact is not configured")
        return cls(
            settings.EASYTRANSACT_API_BASE_URL.rstrip("/"),
            token,
            settings.EASYTRANSACT_HTTP_TIMEOUT_SECONDS,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            with httpx.Client(
                timeout=self.timeout_seconds, follow_redirects=False
            ) as client:
                response = client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=dict(json) if json is not None else None,
                    params=dict(params) if params is not None else None,
                    headers={
                        "Authorization": f"Bearer {self.api_token}",
                        "Accept": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EasyTransactError("Easy Transact request failed") from exc
        if not isinstance(data, dict):
            raise EasyTransactError("Easy Transact returned an invalid response")
        return data

    def create_checkout_link(
        self,
        *,
        description: str,
        amount_xaf: int,
        vendor_reference: str,
        service_code: str = "DEPOSIT",
        success_url: str | None = None,
        cancel_url: str | None = None,
        expires_in_minutes: int = 1440,
    ) -> dict[str, Any]:
        if amount_xaf <= 0:
            raise ValueError("amount_xaf must be positive")
        payload: dict[str, Any] = {
            "description": description[:255],
            "amount": str(Decimal(amount_xaf)),
            "vendor_reference": vendor_reference[:100],
            "currency_code": "XAF",
            "service_code": service_code,
            "expires_in_minutes": expires_in_minutes,
        }
        if success_url:
            payload["success_url"] = success_url
        if cancel_url:
            payload["cancel_url"] = cancel_url
        return self._request(
            "POST", "/api/v1/partner/transactions/checkout-link/", json=payload
        )

    def initiate_transaction(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Call the documented initiate endpoint without guessing undocumented fields."""
        return self._request(
            "POST", "/api/v1/partner/transactions/initiate/", json=payload
        )

    def get_transaction_status(self, *, vendor_reference: str) -> dict[str, Any]:
        # The endpoint is documented as GET, but the supplied excerpt does not
        # expose its query schema. Keep the parameter configurable and fail
        # closed if it is not explicitly enabled.
        parameter = settings.EASYTRANSACT_STATUS_REFERENCE_PARAM
        if not parameter:
            raise EasyTransactError(
                "Easy Transact status query parameter is not configured"
            )
        return self._request(
            "GET",
            "/api/v1/partner/transactions/status/",
            params={parameter: vendor_reference},
        )

    def update_webhook_profile(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        # The endpoint is multipart/form-data and may include a binary logo.
        # The application deliberately does not guess its field encoding.
        raise EasyTransactError(
            "Easy Transact profile update contract is not configured"
        )
