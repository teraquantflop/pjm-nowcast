"""Optional PayAI merchant JWT. Not a chain spending key."""

from __future__ import annotations

import base64
import json
import time
import uuid


class PayAIAuthProvider:
    """Signs short-lived EdDSA JWTs for the PayAI facilitator."""

    def __init__(self, api_key_id: str, api_key_secret: str, ttl: int = 120) -> None:
        from cryptography.hazmat.primitives.serialization import load_der_private_key

        self._kid = api_key_id
        secret = api_key_secret.strip()
        if secret.startswith("payai_sk_"):
            secret = secret[len("payai_sk_"):]
        self._key = load_der_private_key(base64.b64decode(secret), password=None)
        self._ttl = ttl
        self._token: str | None = None
        self._renew_at = 0.0

    @staticmethod
    def _b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    def _mint(self) -> str:
        now = int(time.time())
        header = self._b64(
            json.dumps(
                {"alg": "EdDSA", "typ": "JWT", "kid": self._kid},
                separators=(",", ":"),
            ).encode()
        )
        payload = self._b64(
            json.dumps(
                {
                    "sub": self._kid,
                    "iss": "payai-merchant",
                    "iat": now,
                    "exp": now + self._ttl,
                    "jti": str(uuid.uuid4()),
                },
                separators=(",", ":"),
            ).encode()
        )
        message = f"{header}.{payload}"
        self._token = f"{message}.{self._b64(self._key.sign(message.encode()))}"
        self._renew_at = now + self._ttl - 30
        return self._token

    def _jwt(self) -> str:
        if self._token and time.time() < self._renew_at:
            return self._token
        return self._mint()

    def get_auth_headers(self):
        from x402.http.facilitator_client_base import AuthHeaders

        h = {"Authorization": f"Bearer {self._jwt()}"}
        return AuthHeaders(verify=h, settle=h, supported=h, bazaar=h)
