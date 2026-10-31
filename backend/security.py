"""
HTTP-boundary security helpers (P1-1, P1-2, P1-14).

- resolve_dataset: one shared, traversal-safe resolver for every {dataset_name}
  path parameter. Rejects "..", absolute paths, Windows separators, and any
  encoded variant that survives URL decoding into those forms.
- sanitize_filename: upload filename hardening (no werkzeug dependency).
- require_auth: bearer-token dependency, active only when API_AUTH_TOKEN is set.
- limiter: tiny in-process per-IP rate limiter for expensive endpoints.
"""
import os
import re
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request

import config

_UNSAFE_NAME = re.compile(r"^[\w][\w .()\[\]-]*\.csv$", re.IGNORECASE)


def resolve_dataset(dataset_name: str) -> str:
    """Resolve {dataset_name} to a file inside PUBLIC_DIR, or raise 400/404."""
    if not dataset_name or os.path.basename(dataset_name) != dataset_name:
        raise HTTPException(status_code=400, detail="Invalid dataset name.")
    base = os.path.abspath(config.PUBLIC_DIR)
    candidate = os.path.abspath(os.path.join(base, dataset_name))
    # os.path.join escapes on absolute names; abspath collapses '..' — so the
    # prefix check below is the real gate.
    if os.path.commonpath([base, candidate]) != base:
        raise HTTPException(status_code=400, detail="Invalid dataset name.")
    if not os.path.isfile(candidate):
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return candidate


def require_existing(dataset_name: str) -> str:
    """Alias with the pre-fix name used by write endpoints."""
    return resolve_dataset(dataset_name)


def sanitize_filename(filename: str) -> str:
    """Validate and return safe filename, rejecting path separators, traversal, or invalid names."""
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid file name. Use a plain 'name.csv'.")
    name = filename.strip()
    if not _UNSAFE_NAME.match(name):
        raise HTTPException(status_code=400, detail="Invalid file name. Use a plain 'name.csv'.")
    return name


async def require_auth(request: Request) -> None:
    """Bearer auth on /api/* when API_AUTH_TOKEN is configured; no-op otherwise."""
    if not config.API_AUTH_TOKEN:
        return
    header = request.headers.get("authorization", "")
    if header != f"Bearer {config.API_AUTH_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized.")


class RateLimiter:
    """Per-IP sliding window. In-process; per-worker granularity is acceptable
    for an abort-cost control (not a billing control)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(self, request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = self._hits[ip]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.per_minute:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again shortly.")
        window.append(now)

    def __call__(self, request: Request) -> None:
        self.check(request)


# Shared limiter for AI/simulation endpoints.
expensive_limiter = RateLimiter(config.RATE_LIMIT_PER_MINUTE)
