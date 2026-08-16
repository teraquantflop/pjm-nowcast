#!/usr/bin/env python3
"""Hit L0 routes and show a 402 on a paid route. No keys required."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def get(path: str) -> tuple[int, dict, dict]:
    req = urllib.request.Request(BASE + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode()), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return exc.code, parsed, dict(exc.headers)


def post(path: str, payload: bytes = b"") -> tuple[int, dict, dict]:
    req = urllib.request.Request(
        BASE + path,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return exc.code, parsed, dict(exc.headers)


def main() -> None:
    print(f"probing {BASE}")
    for path in ("/health", "/", "/v1/demo/sample"):
        code, body, _ = get(path)
        print(f"GET  {path:20} -> {code}")
        if path == "/health":
            print("     ", {k: body.get(k) for k in ("status", "db")})
        if path == "/":
            print("     name=", body.get("name"), "prices=", body.get("prices"))
    code, body, headers = post("/v1/nowcast/latest")
    print(f"POST /v1/nowcast/latest  -> {code}  (expect 402 if payments are on)")
    has_pr = any(k.lower() == "payment-required" for k in headers)
    print("     PAYMENT-REQUIRED header:", has_pr)
    if code == 402:
        print("     unpaid paid-route correctly returned 402")
    elif code == 503:
        print("     store empty (data_unavailable) — payments may be disabled")
    elif code == 200:
        print("     200 — X402_DISABLED or free-tier allowed this call")


if __name__ == "__main__":
    main()
