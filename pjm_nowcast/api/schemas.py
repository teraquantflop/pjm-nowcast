"""Public request/response models. Inputs, outputs, units, timestamps only."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from pjm_nowcast import DISCLAIMER

Family = Literal["rto_lmp", "zonal_spread", "rto_load"]


class LatestRequest(BaseModel):
    families: list[Family] | None = Field(
        default=None,
        description="Subset of rto_lmp, zonal_spread, rto_load. Default: all.",
    )


class HistoryRequest(BaseModel):
    families: list[Family] | None = Field(
        default=None,
        description="Subset of rto_lmp, zonal_spread, rto_load. Default: all.",
    )
    windowHours: int = Field(
        default=24,
        ge=1,
        le=72,
        description="Trailing window in hours. L2 maximum is 72.",
    )


class ExtendedHistoryRequest(BaseModel):
    families: list[Family] | None = Field(
        default=None,
        description="Subset of rto_lmp, zonal_spread, rto_load. Default: all.",
    )
    windowHours: int = Field(
        default=168,
        ge=1,
        description="Trailing window in hours, capped by MAX_HISTORY_DAYS.",
    )
    resolution: Literal["native", "hourly"] = Field(
        default="native",
        description="native = one point per poll; hourly = mean per clock hour.",
    )
    compare: Literal["none", "prior_period"] = Field(
        default="none",
        description="If prior_period, include the equal-length window immediately before.",
    )


class ErrorBody(BaseModel):
    error: str
    message: str
    disclaimer: str = DISCLAIMER


def parse_json_body(raw: bytes, model: type[BaseModel]) -> BaseModel:
    if not raw or not raw.strip():
        return model()
    return model.model_validate_json(raw)
