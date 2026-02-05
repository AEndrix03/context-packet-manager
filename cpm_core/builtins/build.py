"""Built-in builder command and registration helpers."""

from __future__ import annotations

import os
import tomllib
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cpm_core.api import cpmcommand
from cpm_core.build import DefaultBuilder, DefaultBuilderConfig
from cpm_core.registry import CPMRegistryEntry, FeatureRegistry
from .commands import _WorkspaceAwareCommand

BUILD_CONFIG_FILE = "build.toml"
SUPPORTED_ARCHIVE_FORMATS = ("tar.gz", "zip")


def _load_build_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except Exception:
        return {}


def _as_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value: Any, default: float | None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def _as_str(value: Any, default: str) -> str:
    if value is None:
        return default
    return str(value)


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("false", "0", "no", "off"):
        return False
    if text in ("true", "1", "yes", "on"):
        return True
    return default


@dataclass(frozen=True)
class _BuildInvocation:
    source: Path
    destination: Path
    config: DefaultBuilderConfig


def _merge_invocation(argv: Any, workspace_root: Path) -> _BuildInvocation:
    config_path = Path(argv.config) if getattr(argv, "config", None) else workspace_root / "config" / BUILD_CONFIG_FILE
    config_data = _load_build_config(config_path)
    source_data = config_data.get("source") or {}
    output_data = config_data.get("output") or {}
    embedding_data = config_data.get("embedding") or {}
    chunking_data = config_data.get("chunking") or {}

    cli_source = getattr(argv, "source", None)
    source_dir = Path(_as_str(cli_source, _as_str(source_data.get("dir"), "."))).resolve()

    cli_dest = getattr(argv, "destination", None)
    if cli_dest:
        destination = Path(cli_dest).resolve()
    else:
        output_dir = _as_str(output_data.get("dir"), "")
        if output_dir:
            destination = Path(output_dir).resolve()
        else:
            destination = workspace_root / "packages" / source_dir.name

    cli_model = getattr(argv, "model", None)
    model_name = _as_str(
        cli_model,
        _as_str(embedding_data.get("model"), DefaultBuilderConfig().model_name),
    )

    cli_max_seq = getattr(argv, "max_seq_length", None)
    max_seq_length = _as_int(
        cli_max_seq,
        _as_int(embedding_data.get("max_seq_length"), DefaultBuilderConfig().max_seq_length),
    )

    cli_lines = getattr(argv, "lines_per_chunk", None)
    lines_per_chunk = _as_int(
        cli_lines,
        _as_int(chunking_data.get("lines_per_chunk"), DefaultBuilderConfig().lines_per_chunk),
    )

    cli_overlap = getattr(argv, "overlap_lines", None)
    overlap_lines = _as_int(
        cli_overlap,
        _as_int(chunking_data.get("overlap_lines"), DefaultBuilderConfig().overlap_lines),
    )

    cli_version = getattr(argv, "packet_version", None)
    version = _as_str(
        cli_version,
        _as_str(output_data.get("version"), DefaultBuilderConfig().version),
    )

    archive = not getattr(argv, "no_archive", False)
    if archive and output_data:
        archive = _as_bool(output_data.get("archive"), archive)
    archive_format = getattr(argv, "archive_format", None) or _as_str(
        output_data.get("archive_format"), DefaultBuilderConfig().archive_format
    )
    if archive_format not in SUPPORTED_ARCHIVE_FORMATS:
        archive_format = DefaultBuilderConfig().archive_format

    cli_embed_url = getattr(argv, "embed_url", None)
    embed_url = _as_str(
        cli_embed_url,
        _as_str(
            embedding_data.get("embed_url"),
            os.environ.get("RAG_EMBED_URL") or DefaultBuilderConfig().embed_url,
        ),
    )

    timeout = getattr(argv, "timeout", None)
    timeout_value = _as_float(timeout, _as_float(embedding_data.get("timeout"), None))

    builder_config = DefaultBuilderConfig(
        model_name=model_name,
        max_seq_length=max_seq_length,
        lines_per_chunk=lines_per_chunk,
        overlap_lines=overlap_lines,
        version=version,
        archive=archive,
        archive_format=archive_format,
        embed_url=embed_url,
        timeout=timeout_value,
    )

    return _BuildInvocation(
        source=source_dir,
        destination=destination,
        config=builder_config,
    )


@cpmcommand(name="build", group="cpm")
class BuildCommand(_WorkspaceAwareCommand):
    """Build context packets from workspace sources."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("--workspace-dir", default=".", help="Workspace root (default: current dir)")
        parser.add_argument("--config", help="Path to build config TOML")
        parser.add_argument("--source", default=".", help="Directory that holds source files")
        parser.add_argument("--destination", help="Packet output directory")
        parser.add_argument("--model", help="Embedding model identifier")
        parser.add_argument("--max-seq-length", type=int, help="Maximum tokens per chunk")
        parser.add_argument("--lines-per-chunk", type=int, help="Number of lines per chunk")
        parser.add_argument("--overlap-lines", type=int, help="Overlap lines between chunks")
        parser.add_argument("--packet-version", dest="packet_version", help="Packet version")
        parser.add_argument("--archive-format", choices=SUPPORTED_ARCHIVE_FORMATS)
        parser.add_argument("--no-archive", action="store_true")
        parser.add_argument("--embed-url", help="Embedding server URL")
        parser.add_argument("--timeout", type=float, help="Embedding request timeout (seconds)")

    def run(self, argv: Any) -> int:
        requested_dir = getattr(argv, "workspace_dir", None)
        workspace_root = self._resolve(requested_dir)
        self.workspace_root = workspace_root
        invocation = _merge_invocation(argv, workspace_root)
        builder = DefaultBuilder(config=invocation.config)
        manifest = builder.build(
            str(invocation.source),
            destination=str(invocation.destination),
        )
        if manifest is None:
            return 1
        return 0


def register_builtin_builders(registry: FeatureRegistry) -> None:
    """Register default builder(s) with the supplied registry."""

    metadata = getattr(DefaultBuilder, "__cpm_feature__", None)
    if metadata is None:
        return
    registry.register(
        CPMRegistryEntry(
            group=metadata["group"],
            name=str(metadata["name"]),
            target=DefaultBuilder,
            kind=str(metadata["kind"]),
            origin="builtin",
        )
    )
