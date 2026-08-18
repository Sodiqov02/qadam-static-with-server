from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from fastapi import HTTPException
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware


BASE_DIR = Path(__file__).resolve().parents[1]
CADDY_IP = "172.30.0.2"
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def require(label: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise AssertionError(f"{label}: {detail}".rstrip())


def service_block(text: str, service: str) -> str:
    match = re.search(rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)", text)
    require(f"{service} service present", match is not None)
    return match.group(1)


async def resolved_client(peer: str, forwarded_for: str | None, trusted: str) -> str:
    captured: list[str] = []

    async def app(scope, receive, send):
        captured.append(scope["client"][0])

    middleware = ProxyHeadersMiddleware(app, trusted_hosts=trusted)
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    scope = {
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": (peer, 12345),
        "server": ("api", 8000),
    }

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_message):
        return None

    await middleware(scope, receive, send)
    require("proxy middleware captured client", len(captured) == 1, captured)
    return captured[0]


def main() -> None:
    finding = "proxy and rate-limit trust boundary"
    try:
        compose_text = (BASE_DIR / "compose.production.yaml").read_text(encoding="utf-8")
        api = service_block(compose_text, "api")
        bot = service_block(compose_text, "bot")
        caddy = service_block(compose_text, "caddy")

        match = re.search(r"FORWARDED_ALLOW_IPS:\s*([^\r\n]+)", api)
        require("FORWARDED_ALLOW_IPS configured", match is not None)
        trusted = match.group(1).strip().strip("\"'")
        trusted_entries = {entry.strip() for entry in trusted.split(",")}
        broad_ranges = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"}
        require("wildcard proxy trust absent", "*" not in trusted_entries, trusted_entries)
        require("broad RFC1918 trust absent", not trusted_entries.intersection(broad_ranges), trusted_entries)
        require("only loopback and Caddy trusted", trusted_entries == {"127.0.0.1", CADDY_IP}, trusted_entries)
        require("API external port reset", "ports: !reset []" in api)
        require("API joins Caddy network", "caddy_api" in api)
        require("Caddy joins Caddy network", "caddy_api" in caddy)
        require("bot excluded from Caddy network", "caddy_api" not in bot)
        require("bot and API share app network", "app_internal" in api and "app_internal" in bot)
        require("Caddy fixed address matches trust", f"ipv4_address: {CADDY_IP}" in caddy)
        require("narrow proxy subnet configured", "subnet: 172.30.0.0/29" in compose_text)

        direct = asyncio.run(resolved_client("198.51.100.10", None, trusted))
        spoofed = asyncio.run(resolved_client("198.51.100.10", "203.0.113.99", trusted))
        proxied_a = asyncio.run(resolved_client(CADDY_IP, "203.0.113.10", trusted))
        proxied_b = asyncio.run(resolved_client(CADDY_IP, "203.0.113.11", trusted))
        require("direct client IP retained", direct == "198.51.100.10", direct)
        require("untrusted forwarded header ignored", spoofed == direct, spoofed)
        require("trusted proxy client A resolved", proxied_a == "203.0.113.10", proxied_a)
        require("trusted proxy client B resolved", proxied_b == "203.0.113.11", proxied_b)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            os.environ["DATABASE_URL"] = f"sqlite:///{(Path(tmp) / 'proxy.db').as_posix()}"
            os.environ["ADMIN_SECRET"] = "proxy_regression_admin_secret"
            from src.api_app import InMemoryRateLimiter

            limiter = InMemoryRateLimiter()
            limiter.check(f"order:{proxied_a}", 1, 60)
            limiter.check(f"order:{proxied_b}", 1, 60)
            require("proxied clients use distinct buckets", len(limiter._events) == 2, list(limiter._events))

            spoof_limiter = InMemoryRateLimiter()
            for fake_header in ("203.0.113.1", "203.0.113.2"):
                resolved = asyncio.run(resolved_client("198.51.100.20", fake_header, trusted))
                spoof_limiter.check(f"order:{resolved}", 2, 60)
            bypassed = True
            try:
                resolved = asyncio.run(resolved_client("198.51.100.20", "203.0.113.3", trusted))
                spoof_limiter.check(f"order:{resolved}", 2, 60)
            except HTTPException as exc:
                bypassed = exc.status_code != 429
            require("spoofed X-Forwarded-For cannot bypass limit", not bypassed)
    except Exception as exc:
        print(json.dumps({"status": "failed", "finding": finding, "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        raise SystemExit(1)
    print(json.dumps({"status": "ok", "finding": finding, "issues": []}, indent=2))


if __name__ == "__main__":
    main()
