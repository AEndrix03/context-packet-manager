from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from cpm_builtin.embeddings.connector import EmbeddingConnector
    import numpy as np

CONFIG_FILENAME = "embeddings.yml"


def _ensure_mapping(data: Any) -> Mapping[str, Any]:
    if isinstance(data, Mapping):
        return data
    raise ValueError("expected mapping for embeddings configuration")


@dataclass
class EmbeddingProviderConfig:
    name: str
    type: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    auth: dict[str, Any] | None = None
    timeout: float | None = None
    batch_size: int | None = None
    model: str | None = None
    dims: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, data: Mapping[str, Any]) -> "EmbeddingProviderConfig":
        raw = _ensure_mapping(data)
        headers: dict[str, str] = {}
        headers_raw = raw.get("headers") or {}
        headers_raw = _ensure_mapping(headers_raw)
        for header_key, header_value in headers_raw.items():
            headers[str(header_key)] = str(header_value)

        extra_entries: dict[str, Any] = {}
        extra_raw = raw.get("extra") or {}
        extra_raw = _ensure_mapping(extra_raw)
        for extra_key, extra_value in extra_raw.items():
            if extra_key is None:
                continue
            extra_entries[str(extra_key)] = extra_value

        auth = raw.get("auth")
        if isinstance(auth, Mapping):
            auth = {str(k): v for k, v in auth.items()}
        elif auth is not None and isinstance(auth, str):
            auth = {"token": auth}

        return cls(
            name=name,
            type=str(raw.get("type", "http")),
            url=str(raw["url"]),
            headers=headers,
            auth=auth,
            timeout=raw.get("timeout"),
            batch_size=raw.get("batch_size"),
            model=raw.get("model"),
            dims=raw.get("dims"),
            extra=extra_entries,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
            "url": self.url,
        }
        if self.headers:
            data["headers"] = self.headers
        if self.auth:
            data["auth"] = self.auth
        if self.timeout is not None:
            data["timeout"] = self.timeout
        if self.batch_size is not None:
            data["batch_size"] = self.batch_size
        if self.model is not None:
            data["model"] = self.model
        if self.dims is not None:
            data["dims"] = self.dims
        if self.extra:
            data["extra"] = self.extra
        return data


@dataclass
class EmbeddingsConfig:
    default: str | None = None
    providers: dict[str, EmbeddingProviderConfig] = field(default_factory=dict)


ConnectorFactory = Callable[
    [EmbeddingProviderConfig], "EmbeddingConnector"
]


class EmbeddingsConfigService:
    def __init__(self, config_dir: Path | str | None = None) -> None:
        base_dir = Path(config_dir) if config_dir else Path(".cpm")
        self.config_dir = base_dir.expanduser()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / CONFIG_FILENAME
        self._config = self._load()

    def _load(self) -> EmbeddingsConfig:
        if not self.config_path.exists():
            return EmbeddingsConfig()
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        default = raw.get("default")
        providers_raw = raw.get("providers") or {}
        providers: dict[str, EmbeddingProviderConfig] = {}
        for name, data in providers_raw.items():
            if not isinstance(name, str):
                continue
            try:
                providers[name] = EmbeddingProviderConfig.from_dict(name, data)
            except KeyError:
                continue
        if default not in providers:
            default = None
        return EmbeddingsConfig(default=default, providers=providers)

    def _persist(self) -> None:
        payload = {
            "default": self._config.default,
            "providers": {
                name: provider.to_dict()
                for name, provider in self._config.providers.items()
            },
        }
        self.config_path.write_text(
            yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
        )

    def list_providers(self) -> list[EmbeddingProviderConfig]:
        return sorted(
            self._config.providers.values(), key=lambda provider: provider.name
        )

    def get_provider(self, name: str) -> EmbeddingProviderConfig:
        try:
            return self._config.providers[name]
        except KeyError as exc:
            raise KeyError(f"provider '{name}' not found") from exc

    def default_provider(self) -> EmbeddingProviderConfig | None:
        if self._config.default:
            return self._config.providers.get(self._config.default)
        return None

    def add_provider(self, provider: EmbeddingProviderConfig, *, set_default: bool = False) -> None:
        self._config.providers[provider.name] = provider
        if set_default or self._config.default is None:
            self._config.default = provider.name
        self._persist()

    def remove_provider(self, name: str) -> None:
        if name not in self._config.providers:
            raise KeyError(f"provider '{name}' not found")
        del self._config.providers[name]
        if self._config.default == name:
            self._config.default = None
        self._persist()

    def set_default_provider(self, name: str) -> None:
        if name not in self._config.providers:
            raise KeyError(f"provider '{name}' not found")
        self._config.default = name
        self._persist()

    def test_provider(
        self,
        name: str,
        connector_factory: ConnectorFactory,
        *,
        texts: Sequence[str] | None = None,
    ) -> tuple[bool, str, "np.ndarray" | None]:
        provider = self.get_provider(name)
        connector = connector_factory(provider)
        test_texts = list(texts or ["test"])
        try:
            matrix = connector.embed_texts(test_texts)
        except Exception as exc:
            return False, str(exc), None
        return True, f"received {matrix.shape}", matrix
