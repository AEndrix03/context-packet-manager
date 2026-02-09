"""Security helpers for OCI refs and local extraction paths."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from .errors import OciSecurityError

_SENSITIVE_KEYS = ("password", "token", "authorization", "bearer")


def host_from_ref(ref: str) -> str:
    value = ref.strip()
    if not value:
        raise OciSecurityError("empty OCI reference")
    host = value.split("/", 1)[0].strip()
    if not host:
        raise OciSecurityError(f"invalid OCI reference: {ref!r}")
    return host.lower()


def assert_allowlisted(ref: str, allowlist_domains: tuple[str, ...]) -> None:
    if not allowlist_domains:
        return
    host = host_from_ref(ref)
    for allowed in allowlist_domains:
        key = allowed.strip().lower()
        if not key:
            continue
        if host == key or host.endswith(f".{key}"):
            return
    raise OciSecurityError(f"registry host '{host}' is not in OCI allowlist")


def safe_output_path(base_dir: Path, relative_path: str) -> Path:
    target = (base_dir / relative_path).resolve()
    root = base_dir.resolve()
    if target == root:
        return target
    if root not in target.parents:
        raise OciSecurityError(f"path traversal blocked for extracted path: {relative_path}")
    return target


def redact_token(value: str) -> str:
    if not value:
        return value
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-2:]}"


def redact_command_for_log(command: list[str]) -> list[str]:
    redacted: list[str] = []
    skip_next = False
    for idx, item in enumerate(command):
        lower = item.lower()
        if skip_next:
            redacted.append("***")
            skip_next = False
            continue
        if lower in {"--password", "--token"}:
            redacted.append(item)
            skip_next = True
            continue
        if any(key in lower for key in _SENSITIVE_KEYS):
            redacted.append("***")
            continue
        if "://" in item:
            parsed = urlsplit(item)
            if parsed.password:
                safe_netloc = parsed.netloc.replace(parsed.password, "***")
                redacted.append(item.replace(parsed.netloc, safe_netloc))
                continue
        redacted.append(item)
    return redacted
