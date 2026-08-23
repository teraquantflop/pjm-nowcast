"""Build x402 facilitator clients: PayAI always; CDP for Base when configured."""

from __future__ import annotations

import logging
from typing import Any

from pjm_nowcast.settings import Settings

log = logging.getLogger("pjm_nowcast.payments")

PAYAI_DEFAULT_URL = "https://facilitator.payai.network"
CDP_FACILITATOR_URL = "https://api.cdp.coinbase.com/platform/v2/x402"
CDP_BASE_NETWORKS = frozenset({"eip155:8453"})


class _NetworkScopedFacilitator:
    """Advertise only selected networks so initialize() maps Base → CDP."""

    def __init__(self, inner: Any, networks: frozenset[str], name: str) -> None:
        self._inner = inner
        self._networks = networks
        self.name = name

    async def verify(self, payload: Any, requirements: Any) -> Any:
        return await self._inner.verify(payload, requirements)

    async def settle(self, payload: Any, requirements: Any) -> Any:
        return await self._inner.settle(payload, requirements)

    def get_supported(self) -> Any:
        try:
            supported = self._inner.get_supported()
        except Exception as exc:
            log.warning(
                "%s facilitator get_supported failed (%s); skipping it",
                self.name,
                exc,
            )
            from x402.schemas.responses import SupportedResponse

            return SupportedResponse(kinds=[])
        kinds = [
            k
            for k in getattr(supported, "kinds", []) or []
            if getattr(k, "network", None) in self._networks
        ]
        try:
            return supported.model_copy(update={"kinds": kinds})
        except Exception:
            supported.kinds = kinds
            return supported


def _payai_client(settings: Settings) -> Any:
    from x402.http import FacilitatorConfig, HTTPFacilitatorClient

    auth = None
    if settings.payai_api_key_id and settings.payai_api_key_secret:
        from pjm_nowcast.payments.payai_auth import PayAIAuthProvider

        auth = PayAIAuthProvider(
            settings.payai_api_key_id, settings.payai_api_key_secret
        )
    cfg = FacilitatorConfig(
        url=settings.facilitator_url or PAYAI_DEFAULT_URL,
        auth_provider=auth,
        identifier="payai",
    )
    return HTTPFacilitatorClient(cfg)


def _cdp_client(settings: Settings) -> Any | None:
    if not settings.cdp_configured:
        return None
    try:
        from cdp.x402 import create_facilitator_config
        from x402.http import HTTPFacilitatorClient
    except Exception as exc:
        log.warning(
            "CDP keys are set but the CDP facilitator client is unavailable (%s); "
            "continuing with PayAI only",
            exc,
        )
        return None

    try:
        cfg = create_facilitator_config(
            api_key_id=settings.cdp_api_key_id,
            api_key_secret=settings.cdp_api_key_secret,
        )
        # CDP returns {url, create_headers}; x402 HTTPFacilitatorClient accepts that dict.
        inner = HTTPFacilitatorClient(cfg)
        return _NetworkScopedFacilitator(inner, CDP_BASE_NETWORKS, "cdp")
    except Exception as exc:
        log.warning(
            "CDP facilitator setup failed (%s); continuing with PayAI only",
            exc,
        )
        return None


def build_facilitator_clients(settings: Settings) -> list[Any]:
    """CDP first (Base only) when configured, then PayAI (Solana + fallback)."""
    id_set = bool(settings.cdp_api_key_id.strip())
    secret_set = bool(settings.cdp_api_key_secret.strip())
    if id_set != secret_set:
        log.warning(
            "CDP_API_KEY_ID and CDP_API_KEY_SECRET must both be set; ignoring CDP"
        )
    clients: list[Any] = []
    cdp = _cdp_client(settings)
    if cdp is not None:
        clients.append(cdp)
        log.info("CDP facilitator enabled for Base (eip155:8453)")
    payai = _payai_client(settings)
    clients.append(payai)
    log.info(
        "PayAI facilitator enabled url=%s (Solana + Polygon; Base fallback=%s)",
        settings.facilitator_url,
        "no" if cdp is not None else "yes",
    )
    return clients
