"""Minimal command line surface for the CPM vNext baseline."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from cpm_builtin import registry_status, run_query
from cpm_builtin.build import build_packet
from cpm_builtin.embeddings import (
    EmbeddingCache,
    EmbeddingProviderConfig,
    EmbeddingsConfigService,
    HttpEmbeddingConnector,
)
from cpm_builtin.packages import PackageManager, parse_package_spec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cpm",
        description="CPM vNext — lightweight CLI for build/query/pkg/embed flows.",
    )
    parser.add_argument("--version", action="version", version="cpm v0.1.0")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = False

    build_cmd = subparsers.add_parser("build", help="run a sample build flow")
    build_cmd.add_argument("--name", default="default", help="packet name placeholder")
    build_cmd.set_defaults(func=_handle_build)

    query_cmd = subparsers.add_parser("query", help="run a sample query")
    query_cmd.add_argument("query", nargs="?", default="hello", help="sample query text")
    query_cmd.set_defaults(func=_handle_query)

    pkg_cmd = subparsers.add_parser("pkg", help="manage local packages")
    pkg_sub = pkg_cmd.add_subparsers(dest="pkg_cmd", required=True)

    pkg_use = pkg_sub.add_parser("use", help="pin/activate a local packet version")
    pkg_use.add_argument("spec", help="name or name@<version|latest>")
    pkg_use.add_argument("--cpm-dir", default=".cpm", help="CPM workspace directory")
    pkg_use.set_defaults(func=_handle_pkg_use)

    pkg_list = pkg_sub.add_parser("list", help="list packages installed under .cpm")
    pkg_list.add_argument("--cpm-dir", default=".cpm", help="CPM workspace directory")
    pkg_list.set_defaults(func=_handle_pkg_list)

    pkg_prune = pkg_sub.add_parser("prune", help="prune old versions while keeping pinned/active")
    pkg_prune.add_argument("name", help="package name")
    pkg_prune.add_argument("--keep", type=int, default=1, help="how many latest versions to keep")
    pkg_prune.add_argument("--cpm-dir", default=".cpm", help="CPM workspace directory")
    pkg_prune.set_defaults(func=_handle_pkg_prune)

    pkg_remove = pkg_sub.add_parser("remove", help="delete a package and its state")
    pkg_remove.add_argument("name", help="package name")
    pkg_remove.add_argument("--cpm-dir", default=".cpm", help="CPM workspace directory")
    pkg_remove.set_defaults(func=_handle_pkg_remove)

    embed = subparsers.add_parser("embed", help="manage embedding providers")
    embed_sub = embed.add_subparsers(dest="embed_cmd", required=True)

    add = embed_sub.add_parser("add", help="register an embedding provider")
    add.add_argument("--name", required=True, help="provider name")
    add.add_argument("--type", default="http", choices=["http"], help="provider type (http)")
    add.add_argument("--url", required=True, help="service endpoint (e.g. http://127.0.0.1:8876)")
    add.add_argument("--model", help="model identifier forwarded to the provider")
    add.add_argument("--dims", type=int, help="expected embedding dimension")
    add.add_argument("--batch-size", type=int, dest="batch_size", help="request batching window")
    add.add_argument("--timeout", type=float, help="request timeout in seconds")
    add.add_argument("--header", action="append", default=[], help="additional header (KEY=VALUE)")
    add.add_argument("--extra", action="append", default=[], help="extra metadata (KEY=VALUE)")
    add.add_argument(
        "--auth-type",
        default="none",
        choices=["none", "basic", "bearer"],
        help="auth scheme (basic/bearer/none)",
    )
    add.add_argument("--auth-username", help="username for basic auth")
    add.add_argument("--auth-password", help="password for basic auth")
    add.add_argument("--auth-token", help="token for bearer auth")
    add.add_argument(
        "--set-default",
        action="store_true",
        help="make this provider the default",
    )
    add.add_argument("--cpm-dir", default=".cpm", help="CPM workspace directory")
    add.set_defaults(func=_handle_embed_add)

    list_cmd = embed_sub.add_parser("list", help="show configured providers")
    list_cmd.add_argument("--cpm-dir", default=".cpm", help="CPM workspace directory")
    list_cmd.set_defaults(func=_handle_embed_list)

    remove = embed_sub.add_parser("remove", help="remove a provider")
    remove.add_argument("--name", required=True, help="provider name")
    remove.add_argument("--cpm-dir", default=".cpm", help="CPM workspace directory")
    remove.set_defaults(func=_handle_embed_remove)

    default_cmd = embed_sub.add_parser("set-default", help="set default provider")
    default_cmd.add_argument("--name", required=True, help="provider name")
    default_cmd.add_argument("--cpm-dir", default=".cpm", help="CPM workspace directory")
    default_cmd.set_defaults(func=_handle_embed_set_default)

    test_cmd = embed_sub.add_parser("test", help="exercise a provider end-to-end")
    test_cmd.add_argument("--name", help="provider name (falls back to default)")
    test_cmd.add_argument(
        "--text",
        action="append",
        default=[],
        help="text to embed (repeat to send multiple)",
    )
    test_cmd.add_argument("--cpm-dir", default=".cpm", help="CPM workspace directory")
    test_cmd.set_defaults(func=_handle_embed_test)

    status_cmd = subparsers.add_parser("status", help="show the current runtime state")
    status_cmd.set_defaults(func=_handle_status)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    func(args)
    return 0


def _handle_build(args: argparse.Namespace) -> None:
    result = build_packet(args.name)
    print("build:", result)


def _handle_query(args: argparse.Namespace) -> None:
    result = run_query(args.query)
    print("query:", result)


def _handle_status(_: argparse.Namespace) -> None:
    print("status:", "stub")


def _handle_embed_add(args: argparse.Namespace) -> None:
    try:
        headers = _parse_key_values(args.header)
        extra = _parse_key_values(args.extra)
    except ValueError as exc:
        print(f"[cpm:embed] error: {exc}")
        return

    auth = _build_auth(args)
    provider = EmbeddingProviderConfig(
        name=args.name,
        type=args.type,
        url=args.url,
        headers=headers,
        auth=auth,
        timeout=args.timeout,
        batch_size=args.batch_size,
        model=args.model,
        dims=args.dims,
        extra=extra,
    )
    service = EmbeddingsConfigService(args.cpm_dir)
    service.add_provider(provider, set_default=args.set_default)
    default = service.default_provider()
    suffix = " (default)" if default and default.name == provider.name else ""
    print(f"[cpm:embed] provider '{provider.name}' registered{suffix}")


def _handle_embed_list(args: argparse.Namespace) -> None:
    service = EmbeddingsConfigService(args.cpm_dir)
    providers = service.list_providers()
    default = service.default_provider()
    default_name = default.name if default else None
    if not providers:
        print("[cpm:embed] no embedding providers configured")
        return
    for provider in providers:
        marker = "*" if provider.name == default_name else " "
        dims = f"dims={provider.dims}" if provider.dims else ""
        model = provider.model or "<unset>"
        print(f"[cpm:embed] {marker} {provider.name} ({provider.type}) {provider.url} model={model} {dims}")


def _handle_embed_remove(args: argparse.Namespace) -> None:
    service = EmbeddingsConfigService(args.cpm_dir)
    try:
        service.remove_provider(args.name)
    except KeyError as exc:
        print(f"[cpm:embed] error: {exc}")
        return
    print(f"[cpm:embed] provider '{args.name}' removed")


def _handle_embed_set_default(args: argparse.Namespace) -> None:
    service = EmbeddingsConfigService(args.cpm_dir)
    try:
        service.set_default_provider(args.name)
    except KeyError as exc:
        print(f"[cpm:embed] error: {exc}")
        return
    print(f"[cpm:embed] default provider set to '{args.name}'")


def _handle_embed_test(args: argparse.Namespace) -> None:
    service = EmbeddingsConfigService(args.cpm_dir)
    provider_name = args.name or (service.default_provider().name if service.default_provider() else None)
    if not provider_name:
        print("[cpm:embed] no provider selected; configure one with `cpm embed add`")
        return
    texts = args.text or ["test embedding"]
    success, message, matrix = service.test_provider(
        provider_name,
        lambda provider: HttpEmbeddingConnector(provider),
        texts=texts,
    )
    if not success or matrix is None:
        print(f"[cpm:embed] test failed: {message}")
        return
    print(f"[cpm:embed] test succeeded: {message}")
    cache_root = Path(args.cpm_dir) / "cache" / "embeddings"
    cache = EmbeddingCache(cache_root=cache_root)
    for text, vector in zip(texts, matrix):
        cache.set(provider_name, text, vector)
    print(f"[cpm:embed] cached {len(texts)} embeddings")


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


def _build_auth(args: argparse.Namespace) -> dict[str, str] | None:
    if args.auth_type == "basic":
        return {
            "type": "basic",
            "username": args.auth_username or "",
            "password": args.auth_password or "",
        }
    if args.auth_type == "bearer":
        token = args.auth_token or ""
        return {"type": "bearer", "token": token}
    return None


def _pkg_manager(args: argparse.Namespace) -> PackageManager:
    return PackageManager(args.cpm_dir)


def _handle_pkg_use(args: argparse.Namespace) -> None:
    manager = _pkg_manager(args)
    try:
        resolved = manager.use(args.spec)
    except ValueError as exc:
        print(f"[cpm:pkg] error: {exc}")
        return
    name, _ = parse_package_spec(args.spec)
    print(f"[cpm:pkg] {name}@{resolved} pinned and activated")


def _handle_pkg_list(args: argparse.Namespace) -> None:
    manager = _pkg_manager(args)
    packages = manager.list_packages()
    if not packages:
        print("[cpm:pkg] no packages installed")
        return
    for pkg in packages:
        versions = ", ".join(pkg.versions)
        pinned = pkg.pinned_version or "-"
        active = pkg.active_version or "-"
        print(f"[cpm:pkg] {pkg.name} versions=[{versions}] pinned={pinned} active={active}")


def _handle_pkg_prune(args: argparse.Namespace) -> None:
    manager = _pkg_manager(args)
    try:
        removed = manager.prune(args.name, keep=args.keep)
    except ValueError as exc:
        print(f"[cpm:pkg] error: {exc}")
        return
    if not removed:
        print(f"[cpm:pkg] nothing pruned for {args.name}")
        return
    print(f"[cpm:pkg] removed versions for {args.name}: {', '.join(removed)}")


def _handle_pkg_remove(args: argparse.Namespace) -> None:
    manager = _pkg_manager(args)
    manager.remove(args.name)
    print(f"[cpm:pkg] package '{args.name}' removed")
