"""ASGI payment gate: 402 before body/schema validation on paid routes.

Official x402 PaymentMiddlewareASGI is used when the SDK is importable and
payments are not disabled. A local stub still emits 402 + PAYMENT-REQUIRED so
tests and the free probe work without hitting a facilitator.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from pjm_nowcast import DISCLAIMER
from pjm_nowcast.db.store import Store
from pjm_nowcast.payments.client_ip import client_ip
from pjm_nowcast.payments.rate_limit import TokenBucket
from pjm_nowcast.payments.routes import (
    BASE_NETWORK,
    BASE_USDC_ADDRESS,
    BASE_USDC_EIP712_EXTRA,
    CHALLENGE_TIMEOUT_SECONDS,
    FREE_TIER_ELIGIBLE,
    PAID_DESCRIPTIONS,
    PAID_ROUTES,
    match_paid_path,
    price_for,
    resource_object,
    resource_url,
    usdc_atomic_amount,
)
from pjm_nowcast.settings import Settings

log = logging.getLogger("pjm_nowcast.payments")

PAYMENT_HEADERS = (
    "payment-signature",
    "x-payment",
    "x-payment-signature",
)


class PaymentGateMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings, store: Store) -> None:
        self.app = app
        self.settings = settings
        self.store = store
        self.bucket = TokenBucket(settings.rate_limit_rps, settings.rate_limit_burst)
        self._x402_app: ASGIApp | None = None
        if not settings.x402_disabled:
            self._x402_app = _try_wrap_x402(app, settings)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        headers = _header_map(scope)

        ip = client_ip(
            headers,
            self.settings,
            fallback=_peer_host(scope),
        )

        paid = match_paid_path(path) if method in {"GET", "POST"} else None

        # Unpaid probes on paid paths (GET or POST) return 402 before body
        # validation and do not consume the rate-limit bucket so scanners
        # can hit all three routes without 429.
        if (
            paid
            and not self.settings.x402_disabled
            and not _has_payment(headers)
        ):
            if method == "GET":
                await _send_402(send, self.settings, paid)
                return
            if method == "POST":
                idem = headers.get("idempotency-key")
                if idem:
                    body = await _read_body(receive)
                    handled = await _try_idempotency(
                        send, self.store, paid, idem, body
                    )
                    if handled:
                        return
                    # No cached hit — still a payment challenge (replay later).
                    replay_early = _replay_receive(body)
                    if not _free_tier_allows(self.store, self.settings, paid, ip):
                        await _send_402(send, self.settings, paid)
                        return
                    if not self.bucket.allow(ip):
                        await _send_json(
                            send,
                            429,
                            {"error": "rate_limited", "message": "Too many requests."},
                        )
                        return
                    await self.app(scope, replay_early, send)
                    return
                if not _free_tier_allows(self.store, self.settings, paid, ip):
                    await _send_402(send, self.settings, paid)
                    return

        if not self.bucket.allow(ip):
            await _send_json(send, 429, {"error": "rate_limited", "message": "Too many requests."})
            return

        if paid is None or method != "POST":
            await self.app(scope, receive, send)
            return

        # Idempotency short-circuit (cached successful response)
        idem = headers.get("idempotency-key")
        body = await _read_body(receive)
        replay = _replay_receive(body)

        if idem and await _try_idempotency(send, self.store, paid, idem, body):
            return

        if self.settings.x402_disabled or not _has_payment(headers):
            # Unpaid POST only reaches here when x402 is off or free-tier allowed.
            await self.app(scope, replay, send)
            return

        # Capture response for idempotency store
        if idem:
            status_box: dict[str, Any] = {}
            chunks: list[bytes] = []

            async def capturing_send(message: dict[str, Any]) -> None:
                if message["type"] == "http.response.start":
                    status_box["status"] = message["status"]
                    await send(message)
                elif message["type"] == "http.response.body":
                    chunks.append(message.get("body") or b"")
                    await send(message)
                    if not message.get("more_body", False):
                        code = int(status_box.get("status") or 200)
                        if 200 <= code < 300:
                            self.store.put_idempotency(
                                idem,
                                paid,
                                _body_hash(body),
                                code,
                                b"".join(chunks).decode("utf-8", errors="replace"),
                                datetime.now(timezone.utc),
                            )

            target = self._x402_app or self.app
            await target(scope, replay, capturing_send)
            return

        target = self._x402_app or self.app
        await target(scope, replay, send)


def _try_wrap_x402(app: ASGIApp, settings: Settings) -> ASGIApp | None:
    """Best-effort official middleware. Failure leaves stub 402 in place."""
    try:
        from x402.http import PaymentOption
        from x402.http.middleware.fastapi import PaymentMiddlewareASGI
        from x402.http.types import RouteConfig
        from x402.mechanisms.evm.exact import ExactEvmServerScheme
        from x402.mechanisms.svm.exact import ExactSvmServerScheme
        from x402.server import x402ResourceServer
    except Exception as exc:
        log.warning("x402 SDK not available (%s); using local 402 stub", exc)
        return None

    try:
        from pjm_nowcast.payments.facilitators import build_facilitator_clients

        clients = build_facilitator_clients(settings)
        server = x402ResourceServer(clients)
        evm_net = "eip155:8453"
        svm_net = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
        if evm_net in settings.network_list and settings.evm_pay_to:
            server.register(evm_net, ExactEvmServerScheme())
        if svm_net in settings.network_list and settings.svm_pay_to:
            server.register(svm_net, ExactSvmServerScheme())

        routes: dict[str, Any] = {}
        for path, _tier in PAID_ROUTES.items():
            accepts = []
            price = price_for(path, settings)
            if settings.evm_pay_to and evm_net in settings.network_list:
                accepts.append(
                    PaymentOption(
                        scheme="exact",
                        pay_to=settings.evm_pay_to,
                        price=price,
                        network=evm_net,
                    )
                )
            if settings.svm_pay_to and svm_net in settings.network_list:
                accepts.append(
                    PaymentOption(
                        scheme="exact",
                        pay_to=settings.svm_pay_to,
                        price=price,
                        network=svm_net,
                    )
                )
            if not accepts:
                continue
            desc = PAID_DESCRIPTIONS[path]
            routes[f"POST {path}"] = RouteConfig(
                accepts=accepts,
                mime_type="application/json",
                description=desc,
                service_name="pjm-nowcast",
                tags=["pjm", "lmp", "load", "spread", "electricity"],
                resource=resource_url(settings, path),
            )
        if not routes:
            return None
        return PaymentMiddlewareASGI(app, routes=routes, server=server)
    except Exception as exc:
        log.warning("x402 middleware setup failed (%s); using local 402 stub", exc)
        return None


def _accept_entry(*, network: str, pay_to: str, price: str) -> dict[str, Any]:
    atomic = usdc_atomic_amount(price)
    entry: dict[str, Any] = {
        "scheme": "exact",
        "network": network,
        "payTo": pay_to,
        "asset": "USDC",
        "price": price,
        "amount": atomic,
        "maxAmountRequired": atomic,
        "maxTimeoutSeconds": CHALLENGE_TIMEOUT_SECONDS,
    }
    if network == BASE_NETWORK:
        # @x402/evm needs the contract + EIP-712 domain, not the ticker string.
        entry["asset"] = BASE_USDC_ADDRESS
        entry["extra"] = dict(BASE_USDC_EIP712_EXTRA)
    return entry


def payment_required_payload(settings: Settings, path: str) -> dict[str, Any]:
    accepts = []
    price = price_for(path, settings)
    if settings.evm_pay_to:
        accepts.append(
            _accept_entry(
                network="eip155:8453",
                pay_to=settings.evm_pay_to,
                price=price,
            )
        )
    if settings.svm_pay_to:
        accepts.append(
            _accept_entry(
                network="solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
                pay_to=settings.svm_pay_to,
                price=price,
            )
        )
    if not accepts:
        # Still advertise so unpaid clients get a 402, not a 400.
        accepts.append(
            _accept_entry(
                network="eip155:8453",
                pay_to="0x0000000000000000000000000000000000000000",
                price=price,
            )
        )
    return {
        "x402Version": 2,
        "error": "Payment required",
        "resource": resource_object(settings, path),
        "accepts": accepts,
        "disclaimer": DISCLAIMER,
    }


async def _try_idempotency(
    send: Send,
    store: Store,
    path: str,
    key: str,
    body: bytes,
) -> bool:
    """Return True if a cached idempotent response was sent."""
    row = store.get_idempotency(key, path)
    if row is None:
        return False
    if str(row["request_hash"]) != _body_hash(body):
        await _send_json(
            send,
            409,
            {
                "error": "idempotency_conflict",
                "message": "Idempotency-Key was reused with a different body.",
                "disclaimer": DISCLAIMER,
            },
        )
        return True
    if row["status_code"] and row["response_json"]:
        await _send_raw(
            send,
            int(row["status_code"]),
            row["response_json"].encode("utf-8"),
            content_type="application/json",
        )
        return True
    return False


def _free_tier_allows(store: Store, settings: Settings, path: str, ip: str) -> bool:
    if path not in FREE_TIER_ELIGIBLE or settings.free_tier_n <= 0:
        return False
    window = _window_start(settings.free_tier_window_seconds)
    bucket = hashlib.sha256(
        f"{settings.free_tier_salt}:{ip}".encode()
    ).hexdigest()
    return store.consume_free_tier(bucket, window, settings.free_tier_n)


async def _send_402(send: Send, settings: Settings, path: str) -> None:
    payload = payment_required_payload(settings, path)
    raw = json.dumps(payload).encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    await send(
        {
            "type": "http.response.start",
            "status": 402,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"payment-required", encoded.encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": raw})


async def _send_json(send: Send, status: int, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": raw})


async def _send_raw(send: Send, status: int, body: bytes, content_type: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", content_type.encode("ascii"))],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _header_map(scope: Scope) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in scope.get("headers") or []:
        out[k.decode("latin1").lower()] = v.decode("latin1")
    return out


def _has_payment(headers: dict[str, str]) -> bool:
    return any(headers.get(h) for h in PAYMENT_HEADERS)


def _peer_host(scope: Scope) -> str:
    client = scope.get("client")
    if client and client[0]:
        return str(client[0])
    return "127.0.0.1"


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            break
        chunks.append(message.get("body") or b"")
        if not message.get("more_body"):
            break
    return b"".join(chunks)


def _replay_receive(body: bytes) -> Receive:
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _body_hash(body: bytes) -> str:
    return hashlib.sha256(body or b"").hexdigest()


def _window_start(window_seconds: int) -> datetime:
    now = datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    start = epoch - (epoch % max(window_seconds, 1))
    return datetime.fromtimestamp(start, tz=timezone.utc)
