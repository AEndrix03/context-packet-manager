from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    return v if v not in (None, "") else default


def _default_env_path() -> str:
    """
    Default: registry/.env relative to current working directory.
    Works when you run from repo root.
    """
    return str(Path(".env"))


def load_env_file(env_file: str | None = None) -> str:
    """
    Load env vars from .env.
    Priority:
      1) explicit env_file argument
      2) env var REGISTRY_ENV_FILE
      3) default registry/.env
    Returns the path used.
    """
    path = env_file or _env("REGISTRY_ENV_FILE") or _default_env_path()
    load_dotenv(dotenv_path=path, override=False)
    return path


@dataclass(frozen=True)
class RegistrySettings:
    # Server
    host: str = "127.0.0.1"
    port: int = 8786

    # DB
    db_path: str = ".database"

    # S3
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "cpm-registry"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    # MinIO safe default
    s3_force_path_style: bool = True

    public_base_url: str | None = None

    @staticmethod
    def from_env(env_file: str | None = None) -> "RegistrySettings":
        load_env_file(env_file)

        host = _env("REGISTRY_HOST", "127.0.0.1") or "127.0.0.1"
        port = int(_env("REGISTRY_PORT", "8786") or "8786")

        db_path = _env("REGISTRY_DB_PATH", ".database") or ".database"

        endpoint = _env("REGISTRY_BUCKET_URL", None)
        bucket = _env("REGISTRY_BUCKET_NAME", "cpm-registry") or "cpm-registry"
        region = _env("REGISTRY_S3_REGION", "us-east-1") or "us-east-1"
        access = _env("REGISTRY_S3_ACCESS_KEY", None)
        secret = _env("REGISTRY_S3_SECRET_KEY", None)

        public_base_url = _env("REGISTRY_PUBLIC_BASE_URL", None)

        return RegistrySettings(
            host=host,
            port=port,
            db_path=db_path,
            s3_endpoint_url=endpoint,
            s3_bucket=bucket,
            s3_region=region,
            s3_access_key=access,
            s3_secret_key=secret,
            public_base_url=public_base_url,
        )
