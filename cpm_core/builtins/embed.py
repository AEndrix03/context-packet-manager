"""Builtin embedding provider management command."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Sequence

from cpm_builtin.embeddings import (
    EmbeddingCache,
    EmbeddingProviderConfig,
    EmbeddingsConfigService,
    HttpEmbeddingConnector,
)
from cpm_core.api import cpmcommand

from .commands import _WorkspaceAwareCommand


@cpmcommand(name="embed", group="cpm")
class EmbedCommand(_WorkspaceAwareCommand):
    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("--workspace-dir", default=".", help="Workspace root directory")
        sub = parser.add_subparsers(dest="embed_cmd", required=True)

        add = sub.add_parser("add", help="Register an embedding provider")
        add.add_argument("--name", required=True)
        add.add_argument("--type", default="http", choices=["http"])
        add.add_argument("--url", required=True)
        add.add_argument("--model")
        add.add_argument("--dims", type=int)
        add.add_argument("--batch-size", type=int, dest="batch_size")
        add.add_argument("--timeout", type=float)
        add.add_argument("--header", action="append", default=[])
        add.add_argument("--extra", action="append", default=[])
        add.add_argument("--auth-type", default="none", choices=["none", "basic", "bearer"])
        add.add_argument("--auth-username")
        add.add_argument("--auth-password")
        add.add_argument("--auth-token")
        add.add_argument("--base-url", help="Explicit OpenAI-compatible base URL")
        add.add_argument("--embeddings-path", default="/v1/embeddings")
        add.add_argument("--models-path", default="/v1/models")
        add.add_argument("--set-default", action="store_true")

        list_cmd = sub.add_parser("list", help="List configured providers")
        list_cmd.add_argument("--show-discovery", action="store_true")

        remove = sub.add_parser("remove", help="Remove provider")
        remove.add_argument("--name", required=True)

        set_default = sub.add_parser("set-default", help="Set default provider")
        set_default.add_argument("--name", required=True)

        test = sub.add_parser("test", help="Exercise provider end-to-end")
        test.add_argument("--name")
        test.add_argument("--text", action="append", default=[])

        refresh = sub.add_parser("refresh", help="Refresh model discovery cache")
        refresh.add_argument("--name")
        refresh.add_argument("--force", action="store_true")

        probe = sub.add_parser("probe", help="Probe provider model dimensions")
        probe.add_argument("--name")

    def run(self, argv: Sequence[str]) -> int:
        workspace_root = self._resolve(getattr(argv, "workspace_dir", None))
        service = EmbeddingsConfigService(workspace_root)
        action = str(getattr(argv, "embed_cmd", "")).strip().lower()
        if action == "add":
            return self._run_add(service, argv)
        if action == "list":
            return self._run_list(service, show_discovery=bool(getattr(argv, "show_discovery", False)))
        if action == "remove":
            return self._run_remove(service, name=str(getattr(argv, "name", "")))
        if action == "set-default":
            return self._run_set_default(service, name=str(getattr(argv, "name", "")))
        if action == "test":
            return self._run_test(service, argv)
        if action == "refresh":
            return self._run_refresh(service, argv)
        if action == "probe":
            return self._run_probe(service, argv)
        print(f"[cpm:embed] unknown subcommand: {action}")
        return 1

    def _run_add(self, service: EmbeddingsConfigService, argv: Any) -> int:
        try:
            headers = _parse_key_values(getattr(argv, "header", None))
            extra = _parse_key_values(getattr(argv, "extra", None))
        except ValueError as exc:
            print(f"[cpm:embed] error: {exc}")
            return 1
        auth = _build_auth(argv)
        provider = EmbeddingProviderConfig(
            name=str(argv.name),
            type=str(argv.type),
            url=str(argv.url),
            headers=headers,
            auth=auth,
            timeout=getattr(argv, "timeout", None),
            batch_size=getattr(argv, "batch_size", None),
            model=getattr(argv, "model", None),
            dims=getattr(argv, "dims", None),
            extra=extra,
            http_base_url=getattr(argv, "base_url", None),
            http_embeddings_path=str(getattr(argv, "embeddings_path", "/v1/embeddings")),
            http_models_path=str(getattr(argv, "models_path", "/v1/models")),
        )
        service.add_provider(provider, set_default=bool(getattr(argv, "set_default", False)))
        print(f"[cpm:embed] provider '{provider.name}' registered")
        return 0

    def _run_list(self, service: EmbeddingsConfigService, *, show_discovery: bool) -> int:
        providers = service.list_providers()
        if not providers:
            print("[cpm:embed] no embedding providers configured")
            return 0
        default = service.default_provider()
        default_name = default.name if default else None
        discovery = service.read_discovery() if show_discovery else {}
        for provider in providers:
            marker = "*" if provider.name == default_name else " "
            model = provider.model or "<unset>"
            dims = f"dims={provider.dims}" if provider.dims else ""
            print(f"[cpm:embed] {marker} {provider.name} ({provider.type}) {provider.url} model={model} {dims}")
            if show_discovery and provider.name in discovery:
                entry = discovery.get(provider.name) or {}
                print(
                    f"[cpm:embed]   discovery source={entry.get('source')} models={entry.get('models', [])} dims={entry.get('dims', {})}"
                )
        return 0

    def _run_remove(self, service: EmbeddingsConfigService, *, name: str) -> int:
        try:
            service.remove_provider(name)
        except KeyError as exc:
            print(f"[cpm:embed] error: {exc}")
            return 1
        print(f"[cpm:embed] provider '{name}' removed")
        return 0

    def _run_set_default(self, service: EmbeddingsConfigService, *, name: str) -> int:
        try:
            service.set_default_provider(name)
        except KeyError as exc:
            print(f"[cpm:embed] error: {exc}")
            return 1
        print(f"[cpm:embed] default provider set to '{name}'")
        return 0

    def _run_test(self, service: EmbeddingsConfigService, argv: Any) -> int:
        default = service.default_provider()
        provider_name = getattr(argv, "name", None) or (default.name if default else None)
        if not provider_name:
            print("[cpm:embed] no provider selected; configure one with `cpm embed add`")
            return 1
        texts = getattr(argv, "text", None) or ["test embedding"]
        success, message, matrix = service.test_provider(
            provider_name,
            lambda provider: HttpEmbeddingConnector(provider),
            texts=texts,
        )
        if not success or matrix is None:
            print(f"[cpm:embed] test failed: {message}")
            return 1
        print(f"[cpm:embed] test succeeded: {message}")
        cache_root = service.discovery_cache_path.parent
        cache = EmbeddingCache(cache_root=cache_root)
        for text, vector in zip(texts, matrix):
            cache.set(provider_name, text, vector)
        return 0

    def _run_refresh(self, service: EmbeddingsConfigService, argv: Any) -> int:
        provider = getattr(argv, "name", None)
        refreshed = service.refresh_discovery(provider_name=provider, force=bool(getattr(argv, "force", False)))
        print(f"[cpm:embed] refreshed providers: {', '.join(sorted(refreshed.keys())) or '<none>'}")
        return 0

    def _run_probe(self, service: EmbeddingsConfigService, argv: Any) -> int:
        provider = getattr(argv, "name", None)
        refreshed = service.refresh_discovery(provider_name=provider, force=True)
        for name, payload in refreshed.items():
            print(f"[cpm:embed] {name} models={payload.get('models', [])} dims={payload.get('dims', {})}")
        return 0


def _parse_key_values(items: Sequence[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if not items:
        return result
    for entry in items:
        if "=" not in entry:
            raise ValueError(f"invalid key=value pair: {entry}")
        key, value = entry.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _build_auth(args: Any) -> dict[str, str] | None:
    auth_type = str(getattr(args, "auth_type", "none")).strip().lower()
    if auth_type == "basic":
        return {
            "type": "basic",
            "username": str(getattr(args, "auth_username", "") or ""),
            "password": str(getattr(args, "auth_password", "") or ""),
        }
    if auth_type == "bearer":
        return {"type": "bearer", "token": str(getattr(args, "auth_token", "") or "")}
    return None
