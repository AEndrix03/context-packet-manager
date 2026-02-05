from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

import requests
from requests import RequestException, Response
from requests.auth import AuthBase

log = logging.getLogger(__name__)


class RegistryClientError(Exception):
    """Base exception for registry client failures."""


class RegistryDownloadError(RegistryClientError):
    """Raised when a download fails or delivers invalid data."""


class RegistryPackageVersion:
    """Metadata for a single package version reported by the registry."""

    __slots__ = (
        "name",
        "version",
        "sha256",
        "size_bytes",
        "published_at",
        "yanked",
        "object_key",
        "checksum",
    )

    def __init__(
        self,
        *,
        name: str,
        version: str,
        sha256: str | None,
        size_bytes: int | None,
        published_at: str | None,
        yanked: bool,
        object_key: str | None,
        checksum: str | None,
    ) -> None:
        self.name = name
        self.version = version
        self.sha256 = sha256
        self.size_bytes = size_bytes
        self.published_at = published_at
        self.yanked = yanked
        self.object_key = object_key
        self.checksum = checksum

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RegistryPackageVersion":
        size_bytes = data.get("size_bytes")
        if size_bytes is not None:
            try:
                size_bytes = int(size_bytes)
            except (TypeError, ValueError):
                size_bytes = None
        return cls(
            name=str(data.get("name", "")),
            version=str(data.get("version", "")),
            sha256=data.get("sha256"),
            size_bytes=size_bytes,
            published_at=data.get("published_at"),
            yanked=bool(data.get("yanked")),
            object_key=data.get("object_key"),
            checksum=data.get("checksum"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "published_at": self.published_at,
            "yanked": self.yanked,
            "object_key": self.object_key,
            "checksum": self.checksum,
        }


@dataclass(frozen=True)
class RegistryPackageList:
    name: str
    versions: Tuple[RegistryPackageVersion, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RegistryPackageList":
        name = str(data.get("name", ""))
        raw_versions = data.get("versions") or []
        versions = tuple(
            RegistryPackageVersion.from_dict(v)
            for v in raw_versions
            if isinstance(v, Mapping)
        )
        return cls(name=name, versions=versions)


@dataclass
class RegistryClient:
    """HTTP client for the CPM registry service."""

    base_url: str
    timeout: float | Tuple[float, float] = 10.0
    auth: AuthBase | Tuple[str, str] | None = None
    token: str | None = None
    session: requests.Session = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.session = requests.Session()
        if self.auth is not None:
            self.session.auth = self.auth
        if self.token:
            self.session.headers.setdefault("Authorization", f"Bearer {self.token}")

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _timeout_value(self, override: float | Tuple[float, float] | None) -> float | Tuple[float, float]:
        return override if override is not None else self.timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        ok_statuses: Sequence[int] = tuple(range(200, 300)),
        timeout: float | Tuple[float, float] | None = None,
        **kwargs: Any,
    ) -> Response:
        url = self._url(path)
        try:
            resp = self.session.request(
                method,
                url,
                timeout=self._timeout_value(timeout),
                **kwargs,
            )
        except RequestException as exc:
            raise RegistryClientError(f"{method} {url} failed: {exc}") from exc

        if resp.status_code not in ok_statuses:
            raise RegistryClientError(
                f"{method} {url} returned {resp.status_code}: {resp.text}"
            )

        return resp

    def _raise_download_error(self, resp: Response) -> None:
        raise RegistryDownloadError(
            f"download failed: {resp.status_code} {resp.text}"
        )

    def exists(self, name: str, version: str) -> bool:
        try:
            resp = self.session.head(self._url(f"/v1/packages/{name}/{version}"), timeout=self.timeout)
        except RequestException as exc:
            raise RegistryClientError(f"HEAD {name}@{version} failed: {exc}") from exc
        return resp.status_code == 200

    def publish(
        self,
        name: str,
        version: str,
        file_path: str,
        *,
        overwrite: bool = False,
    ) -> RegistryPackageVersion:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(file_path)

        params = {"overwrite": "true"} if overwrite else None
        with path.open("rb") as f:
            files = {"file": (path.name, f, "application/gzip")}
            url = f"/v1/packages/{name}/{version}"
            log.info("Publishing %s@%s -> %s overwrite=%s", name, version, url, overwrite)
            resp = self._request("POST", url, files=files, params=params, timeout=120)

        return RegistryPackageVersion.from_dict(resp.json())

    def download(self, name: str, version: str, out_path: str, *, chunk_size: int = 1024 * 1024) -> Path:
        url = self._url(f"/v1/packages/{name}/{version}/download")
        try:
            resp = self.session.get(url, stream=True, timeout=self.timeout)
        except RequestException as exc:
            raise RegistryDownloadError(f"download {name}@{version} failed: {exc}") from exc

        if resp.status_code >= 400:
            self._raise_download_error(resp)

        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
        return target

    def list(self, name: str, *, include_yanked: bool = False) -> RegistryPackageList:
        params = {"include_yanked": str(include_yanked).lower()}
        resp = self._request("GET", f"/v1/packages/{name}", params=params)
        return RegistryPackageList.from_dict(resp.json())

    def get_version(self, name: str, version: str) -> RegistryPackageVersion:
        resp = self._request("GET", f"/v1/packages/{name}/{version}")
        return RegistryPackageVersion.from_dict(resp.json())
