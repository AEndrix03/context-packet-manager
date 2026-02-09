"""OCI client datatypes and configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class OciClientConfig:
    timeout_seconds: float = 30.0
    max_retries: int = 2
    backoff_seconds: float = 0.2
    insecure: bool = False
    allowlist_domains: tuple[str, ...] = ()
    max_artifact_size_bytes: int | None = None
    username: str | None = None
    password: str | None = None
    token: str | None = None


@dataclass(frozen=True)
class OciPullResult:
    ref: str
    digest: str | None
    files: tuple[Path, ...]


@dataclass(frozen=True)
class OciPushResult:
    ref: str
    digest: str


@dataclass(frozen=True)
class OciArtifactSpec:
    files: tuple[Path, ...]
    media_types: Mapping[str, str] = field(default_factory=dict)
