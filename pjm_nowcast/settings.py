"""Environment-backed settings. Server process must never hold chain private keys."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

FORBIDDEN_KEY_NAMES = (
    "SVM_PRIVATE_KEY",
    "EVM_PRIVATE_KEY",
    "SOLANA_PRIVATE_KEY",
    "ETH_PRIVATE_KEY",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    port: int = 8000
    env: Literal["development", "production", "test"] = "development"

    data_dir: Path = Path("./var")
    database_path: Path | None = None

    public_base_url: str = "http://localhost:8000"
    public_icon_url: str | None = None

    cors_origin: str = ""
    trust_proxy: bool = False

    run_poller: bool = True
    poll_interval_seconds: int = 1800
    poll_jitter_seconds: int = 60
    poll_url: str = "https://www.pjm.com/markets-and-operations"
    request_timeout_sec: float = 25.0
    mock_mode: bool = False
    poll_carry_forward: bool = False

    retention_days: int = 30
    max_history_days: int = 30
    stale_after_seconds: int = 10800
    zonal_zones: str = "BGE,COMED,DOM,PEPCO,PSEG,JCPL"
    min_zones_for_spread: int = 4
    spread_k: float = 1.25
    spread_abs_usd: float = 15.0
    snapshot_path: Path | None = None
    pjm_nowcast_reset_hmm: bool = False

    pay_to_svm_address: str = ""
    pay_to_evm_address: str = ""
    pay_to_address: str = ""
    networks: str = (
        "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp,eip155:8453"
    )
    facilitator_url: str = "https://facilitator.payai.network"
    price_l1: str = "$0.02"
    price_l2: str = "$0.10"
    price_l3: str = "$0.25"

    free_demo_enabled: bool = True
    free_tier_n: int = 0
    free_tier_window_seconds: int = 86400
    free_tier_salt: str = "pjm-nowcast-free-tier"

    mcp_enabled: bool = True
    mcp_path: str = "/mcp"

    rate_limit_rps: float = 5.0
    rate_limit_burst: int = 20

    payai_api_key_id: str = ""
    payai_api_key_secret: str = ""

    # Coinbase CDP facilitator (Base). Optional; PayAI-only if unset.
    cdp_api_key_id: str = ""
    cdp_api_key_secret: str = ""

    log_level: str = "INFO"

    # Test / local only. Production start fails if true.
    x402_disabled: bool = False

    optionbook_id: str = ""

    @field_validator("mcp_path")
    @classmethod
    def _slash_path(cls, v: str) -> str:
        v = v.strip() or "/mcp"
        return v if v.startswith("/") else f"/{v}"

    @model_validator(mode="after")
    def _resolve_and_guard(self) -> "Settings":
        for name in FORBIDDEN_KEY_NAMES:
            if os.environ.get(name):
                raise RuntimeError(
                    f"{name} must not be set on the server process. "
                    "Client signing keys stay in a local test-client .env only."
                )
        if self.database_path is None:
            object.__setattr__(
                self, "database_path", self.data_dir / "pjm-nowcast.sqlite"
            )
        if self.snapshot_path is None:
            object.__setattr__(self, "snapshot_path", self.data_dir / "snapshot.json")
        if self.env == "production":
            if self.x402_disabled:
                raise RuntimeError(
                    "X402_DISABLED cannot be true when ENV=production"
                )
            if not self.public_base_url or "localhost" in self.public_base_url:
                raise RuntimeError(
                    "PUBLIC_BASE_URL must be the public origin in production"
                )
            if (
                not self.pay_to_svm_address
                and not self.pay_to_evm_address
                and not self.pay_to_address
            ):
                raise RuntimeError(
                    "At least one PAY_TO_* address is required in production"
                )
        return self

    @property
    def zone_list(self) -> tuple[str, ...]:
        return tuple(
            z.strip().upper() for z in self.zonal_zones.split(",") if z.strip()
        )

    @property
    def network_list(self) -> list[str]:
        return [n.strip() for n in self.networks.split(",") if n.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origin.split(",") if o.strip()]

    @property
    def evm_pay_to(self) -> str:
        return self.pay_to_evm_address or (
            self.pay_to_address if self.pay_to_address.startswith("0x") else ""
        )

    @property
    def svm_pay_to(self) -> str:
        if self.pay_to_svm_address:
            return self.pay_to_svm_address
        if self.pay_to_address and not self.pay_to_address.startswith("0x"):
            return self.pay_to_address
        return ""

    @property
    def l2_max_hours(self) -> int:
        return 72

    @property
    def l3_max_hours(self) -> int:
        return self.max_history_days * 24

    @property
    def default_l1_window_hours(self) -> int:
        return 24

    @property
    def cdp_configured(self) -> bool:
        return bool(self.cdp_api_key_id.strip() and self.cdp_api_key_secret.strip())

    def facilitator_status(self) -> dict[str, object]:
        """Public names only — never include secrets."""
        cdp = self.cdp_configured
        return {
            "payai": True,
            "cdp": cdp,
            "base": "cdp" if cdp else "payai",
            "solana": "payai",
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
