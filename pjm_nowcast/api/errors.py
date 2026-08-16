from __future__ import annotations

from fastapi.responses import JSONResponse

from pjm_nowcast import DISCLAIMER


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": code,
            "message": message,
            "disclaimer": DISCLAIMER,
        },
    )


def data_unavailable() -> JSONResponse:
    return error_response(
        503,
        "data_unavailable",
        "No observations are stored yet. The background poller has not written a successful sample.",
    )
