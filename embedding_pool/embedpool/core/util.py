from __future__ import annotations

import os
import time
from pathlib import Path


def ensure_dirs(*paths: str) -> None:
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)


def now_ms() -> int:
    return int(time.time() * 1000)


def env_override_pool_url(default_url: str) -> str:
    v = (os.environ.get("EMBEDPOOL_URL") or "").strip()
    return v or default_url


def safe_int(x, default: int) -> int:
    try:
        return int(x)
    except Exception:
        return default


def safe_bool(x, default: bool) -> bool:
    if x is None:
        return default
    if isinstance(x, bool):
        return x
    s = str(x).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default
