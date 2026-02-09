"""Built-in builder command and registration helpers."""

from __future__ import annotations

import json
import os
import tomllib
from datetime import datetime, timezone
from argparse import ArgumentParser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cpm_core.api import cpmcommand
from cpm_builtin.embeddings import EmbeddingClient, VALID_EMBEDDING_MODES
from cpm_builtin.embeddings.config import EmbeddingsConfigService
from cpm_core.build import DefaultBuilder, DefaultBuilderConfig, embed_packet_from_chunks
from cpm_core.packet import (
    DEFAULT_LOCKFILE_NAME,
    artifact_hashes,
    build_resolved_plan,
    load_lock,
    lock_has_non_deterministic_sections,
    render_lock,
    verify_artifacts,
    verify_lock_against_plan,
    write_lock,
)
from cpm_core.registry import AmbiguousFeatureError, CPMRegistryEntry, FeatureNotFoundError, FeatureRegistry
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


def _read_simple_yml(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return out
    except UnicodeDecodeError:
        lines = path.read_text(encoding="latin-1").splitlines()

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def _write_simple_yml(path: Path, kv: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for key, value in kv.items():
            handle.write(f"{key}: {value}\n")


@dataclass(frozen=True)
class _BuildInvocation:
    source: Path
    destination_root: Path
    packet_dir: Path
    packet_name: str
    packet_version: str
    description: str
    config: DefaultBuilderConfig
    config_payload: dict[str, Any]
    builder: str


def _resolve_default_embedding_provider(workspace_root: Path) -> Any:
    candidates = [workspace_root, workspace_root / "config"]
    if workspace_root.name == ".cpm":
        candidates.extend([workspace_root.parent, workspace_root.parent / ".cpm" / "config"])
    else:
        candidates.extend([workspace_root / ".cpm", workspace_root / ".cpm" / "config"])

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            provider = EmbeddingsConfigService(resolved).default_provider()
        except Exception:
            provider = None
        if provider is not None:
            return provider
    return None


def _merge_invocation(argv: Any, workspace_root: Path) -> _BuildInvocation:
    config_path = Path(argv.config) if getattr(argv, "config", None) else workspace_root / "config" / BUILD_CONFIG_FILE
    config_data = _load_build_config(config_path)
    source_data = config_data.get("source") or {}
    output_data = config_data.get("output") or {}
    embedding_data = config_data.get("embedding") or {}
    embeddings_data = config_data.get("embeddings") or {}
    chunking_data = config_data.get("chunking") or {}

    packet_name = _as_str(getattr(argv, "name", None), _as_str(output_data.get("name"), "")).strip()
    packet_version = _as_str(
        getattr(argv, "packet_version", None),
        _as_str(output_data.get("version"), ""),
    ).strip()
    description = _as_str(getattr(argv, "description", None), _as_str(output_data.get("description"), "")).strip()

    cli_source = getattr(argv, "source", None)
    source_dir = Path(_as_str(cli_source, _as_str(source_data.get("dir"), "."))).resolve()

    cli_dest = getattr(argv, "destination", None)
    if cli_dest:
        destination_root = Path(cli_dest).resolve()
    else:
        output_dir = _as_str(output_data.get("dir"), "dist")
        destination_root = (workspace_root / output_dir).resolve()
    packet_dir = destination_root / packet_name / packet_version

    cli_model = getattr(argv, "model", None)
    if cli_model is None:
        cli_model = getattr(argv, "model_name", None)
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

    archive = not getattr(argv, "no_archive", False)
    if output_data:
        archive = _as_bool(output_data.get("archive"), archive)
    archive_format = getattr(argv, "archive_format", None) or _as_str(
        output_data.get("archive_format"), DefaultBuilderConfig().archive_format
    )
    if archive_format not in SUPPORTED_ARCHIVE_FORMATS:
        archive_format = DefaultBuilderConfig().archive_format

    default_provider = _resolve_default_embedding_provider(workspace_root)

    cli_embed_url = getattr(argv, "embed_url", None)
    embed_url = _as_str(
        cli_embed_url,
        _as_str(
            embeddings_data.get("url")
            or embeddings_data.get("embed_url")
            or embedding_data.get("embed_url"),
            _as_str(default_provider.url if default_provider is not None else None, ""),
        ),
    )
    if not embed_url:
        embed_url = _as_str(os.environ.get("RAG_EMBED_URL"), DefaultBuilderConfig().embed_url)

    cli_embeddings_mode = getattr(argv, "embeddings_mode", None)
    embeddings_mode = _as_str(
        cli_embeddings_mode,
        _as_str(
            embeddings_data.get("mode"),
            _as_str(default_provider.type if default_provider is not None else None, ""),
        ),
    ).strip().lower()
    if not embeddings_mode:
        embeddings_mode = _as_str(os.environ.get("RAG_EMBED_MODE"), DefaultBuilderConfig().embeddings_mode).strip().lower()
    if embeddings_mode not in VALID_EMBEDDING_MODES:
        embeddings_mode = DefaultBuilderConfig().embeddings_mode

    timeout = getattr(argv, "timeout", None)
    timeout_value = _as_float(
        timeout,
        _as_float(
            embeddings_data.get("timeout"),
            _as_float(
                embedding_data.get("timeout"),
                _as_float(default_provider.resolved_http_timeout if default_provider is not None else None, None),
            ),
        ),
    )

    builder_config = DefaultBuilderConfig(
        model_name=model_name,
        max_seq_length=max_seq_length,
        lines_per_chunk=lines_per_chunk,
        overlap_lines=overlap_lines,
        version=packet_version,
        packet_name=packet_name,
        description=description or None,
        archive=archive,
        archive_format=archive_format,
        embed_url=embed_url,
        embeddings_mode=embeddings_mode,
        timeout=timeout_value,
    )

    return _BuildInvocation(
        source=source_dir,
        destination_root=destination_root,
        packet_dir=packet_dir,
        packet_name=packet_name,
        packet_version=packet_version,
        description=description,
        config=builder_config,
        config_payload=config_data,
        builder=_as_str(getattr(argv, "builder", None), "cpm:default-builder"),
    )


def _list_builder_specs(workspace_root: Path) -> list[str]:
    from cpm_core.app import CPMApp

    app = CPMApp(start_dir=workspace_root)
    app.bootstrap()
    entries = [entry for entry in app.feature_registry.entries() if entry.kind == "builder"]
    names = sorted({entry.name for entry in entries})
    qualified = sorted(entry.qualified_name for entry in entries)
    return sorted(set(names + qualified))


def _resolve_builder_entry(spec: str, workspace_root: Path) -> CPMRegistryEntry | None:
    from cpm_core.app import CPMApp

    app = CPMApp(start_dir=workspace_root)
    app.bootstrap()
    try:
        entry = app.feature_registry.resolve(spec)
    except (FeatureNotFoundError, AmbiguousFeatureError):
        return None
    if entry.kind != "builder":
        return None
    return entry


def _resolve_builder_plugin_version(builder_entry: CPMRegistryEntry, workspace_root: Path) -> str:
    if builder_entry.origin == "builtin":
        return "builtin"
    from cpm_core.app import CPMApp

    app = CPMApp(start_dir=workspace_root)
    app.bootstrap()
    for record in app.plugin_manager.plugin_records():
        if record.id != builder_entry.origin:
            continue
        if record.manifest is not None:
            return record.manifest.version
        break
    return "unknown"


def _build_lock_plan(
    invocation: _BuildInvocation,
    *,
    builder_entry: CPMRegistryEntry,
    builder_plugin_version: str,
) -> Any:
    merged_config = {
        "build_config": invocation.config_payload,
        "resolved_config": asdict(invocation.config),
        "builder": builder_entry.qualified_name,
        "source": invocation.source.as_posix(),
    }
    return build_resolved_plan(
        source_path=invocation.source,
        packet_name=invocation.packet_name,
        packet_version=invocation.packet_version,
        packet_id=invocation.packet_name,
        build_profile=builder_entry.qualified_name,
        builder_plugin=builder_entry.qualified_name,
        builder_plugin_version=builder_plugin_version,
        config_payload=merged_config,
        model_provider="sentence-transformers",
        model_name=invocation.config.model_name,
        model_dtype="float16",
        normalize=True,
        max_seq_length=invocation.config.max_seq_length,
    )


def _execute_builder(invocation: _BuildInvocation, builder_entry: CPMRegistryEntry, argv: Any) -> bool:
    builder_cls = builder_entry.target
    if builder_cls is DefaultBuilder:
        builder = builder_cls(config=invocation.config)
        manifest = builder.build(
            str(invocation.source),
            destination=str(invocation.packet_dir),
        )
        return manifest is not None

    builder = builder_cls()
    setattr(argv, "destination", str(invocation.packet_dir))
    setattr(argv, "source", str(invocation.source))
    setattr(argv, "packet_version", invocation.packet_version)
    setattr(argv, "name", invocation.packet_name)
    setattr(argv, "description", invocation.description)
    setattr(argv, "model_name", invocation.config.model_name)
    setattr(argv, "embed_url", invocation.config.embed_url)
    setattr(argv, "embeddings_mode", invocation.config.embeddings_mode)
    setattr(argv, "max_seq_length", invocation.config.max_seq_length)
    setattr(argv, "timeout", invocation.config.timeout)

    run_method = getattr(builder, "run", None)
    if callable(run_method):
        return int(run_method(argv)) == 0

    manifest = builder.build(str(invocation.source), destination=str(invocation.packet_dir))
    if builder_entry.origin == "builtin" and manifest is None:
        return False
    return True


def _print_verify_errors(errors: tuple[str, ...]) -> None:
    for item in errors:
        print(f"[cpm:build] {item}")


def _update_packet_description(packet_dir: Path, description: str) -> int:
    if not packet_dir.exists():
        print(f"[cpm:build] packet directory not found: {packet_dir}")
        return 1

    cpm_yml_path = packet_dir / "cpm.yml"
    data = _read_simple_yml(cpm_yml_path)
    if data:
        data["description"] = description
        _write_simple_yml(cpm_yml_path, data)

    manifest_path = packet_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[cpm:build] invalid manifest.json: {exc}")
            return 1
        cpm = manifest.get("cpm") if isinstance(manifest.get("cpm"), dict) else {}
        cpm["description"] = description
        manifest["cpm"] = cpm
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[cpm:build] description updated for {packet_dir}")
    return 0


@cpmcommand(name="build", group="cpm")
class BuildCommand(_WorkspaceAwareCommand):
    """Build and manage context packets."""

    @classmethod
    def _configure_run_options(cls, parser: ArgumentParser, *, required: bool) -> None:
        parser.add_argument("--builder", default="cpm:default-builder", help="Builder name or group:name")
        parser.add_argument("--source", default=".", help="Source directory (default: current dir)")
        parser.add_argument("--destination", default="dist", help="Destination root (default: ./dist)")
        parser.add_argument("--name", required=required, help="Packet name")
        parser.add_argument(
            "--packet-version",
            "--version",
            dest="packet_version",
            required=required,
            help="Packet version",
        )
        parser.add_argument("--description", help="Packet description")
        parser.add_argument("--model", "--model-name", dest="model", help="Embedding model identifier")
        parser.add_argument("--max-seq-length", type=int, help="Maximum tokens per chunk")
        parser.add_argument("--lines-per-chunk", type=int, help="Number of lines per chunk")
        parser.add_argument("--overlap-lines", type=int, help="Overlap lines between chunks")
        parser.add_argument("--archive-format", choices=SUPPORTED_ARCHIVE_FORMATS)
        parser.add_argument("--no-archive", action="store_true")
        parser.add_argument("--embed-url", help="Embedding server URL")
        parser.add_argument("--embeddings-mode", choices=VALID_EMBEDDING_MODES, help="Embedding transport mode")
        parser.add_argument("--timeout", type=float, help="Embedding request timeout (seconds)")
        parser.add_argument("--lockfile", default=DEFAULT_LOCKFILE_NAME, help="Lockfile name inside packet directory")
        parser.add_argument("--frozen-lockfile", action="store_true", help="Require an up-to-date deterministic lockfile")
        parser.add_argument("--update-lock", action="store_true", help="Regenerate lockfile from current inputs/config")

    @classmethod
    def _configure_embed_options(cls, parser: ArgumentParser) -> None:
        parser.add_argument("--source", required=True, help="Packet directory containing docs.jsonl")
        parser.add_argument("--name", help="Override packet name")
        parser.add_argument("--packet-version", "--version", dest="packet_version", help="Override packet version")
        parser.add_argument("--description", help="Override packet description")
        parser.add_argument("--model", "--model-name", dest="model", help="Embedding model identifier")
        parser.add_argument("--max-seq-length", type=int, help="Maximum tokens per chunk")
        parser.add_argument("--archive-format", choices=SUPPORTED_ARCHIVE_FORMATS)
        parser.add_argument("--no-archive", action="store_true")
        parser.add_argument("--embed-url", help="Embedding server URL")
        parser.add_argument("--embeddings-mode", choices=VALID_EMBEDDING_MODES, help="Embedding transport mode")
        parser.add_argument("--timeout", type=float, help="Embedding request timeout (seconds)")
        parser.add_argument("--lockfile", default=DEFAULT_LOCKFILE_NAME, help="Lockfile name inside packet directory")
        parser.add_argument("--update-lock", action="store_true", help="Update lockfile artifact hashes if present")

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("--workspace-dir", default=".", help="Workspace root (default: current dir)")
        parser.add_argument("--config", help="Path to build config TOML")
        cls._configure_run_options(parser, required=False)

        sub = parser.add_subparsers(dest="build_cmd")

        run = sub.add_parser("run", help="Build a packet")
        cls._configure_run_options(run, required=True)

        embed = sub.add_parser("embed", help="Generate vectors/faiss from existing packet chunks")
        cls._configure_embed_options(embed)

        lock = sub.add_parser("lock", help="Generate or update packet lockfile without building artifacts")
        cls._configure_run_options(lock, required=True)

        verify = sub.add_parser("verify", help="Verify lockfile coherence and artifact integrity")
        cls._configure_run_options(verify, required=True)

        describe = sub.add_parser("describe", help="Set or update packet description")
        describe.add_argument("--destination", default="dist", help="Destination root (default: ./dist)")
        describe.add_argument("--name", required=True, help="Packet name")
        describe.add_argument("--packet-version", "--version", dest="packet_version", required=True, help="Packet version")
        describe.add_argument("--description", required=True, help="Description text")

        inspect = sub.add_parser("inspect", help="Print resolved packet path")
        inspect.add_argument("--destination", default="dist", help="Destination root (default: ./dist)")
        inspect.add_argument("--name", required=True, help="Packet name")
        inspect.add_argument("--packet-version", "--version", dest="packet_version", required=True, help="Packet version")

        parser.set_defaults(build_cmd="run")

    def run(self, argv: Any) -> int:
        requested_dir = getattr(argv, "workspace_dir", None)
        workspace_root = self._resolve(requested_dir)
        self.workspace_root = workspace_root

        action = str(getattr(argv, "build_cmd", "run") or "run")
        if action == "describe":
            destination = Path(str(getattr(argv, "destination", "dist") or "dist"))
            root = destination if destination.is_absolute() else (workspace_root / destination)
            packet_dir = root / str(getattr(argv, "name", "")) / str(getattr(argv, "packet_version", ""))
            return _update_packet_description(packet_dir, str(getattr(argv, "description", "")).strip())

        if action == "inspect":
            destination = Path(str(getattr(argv, "destination", "dist") or "dist"))
            root = destination if destination.is_absolute() else (workspace_root / destination)
            packet_dir = root / str(getattr(argv, "name", "")) / str(getattr(argv, "packet_version", ""))
            print(f"[cpm:build] packet_dir={packet_dir.resolve()}")
            print(f"[cpm:build] exists={packet_dir.exists()}")
            return 0

        if action == "embed":
            raw_source = str(getattr(argv, "source", "") or "").strip()
            if not raw_source:
                print("[cpm:build] --source is required for build embed")
                return 1
            packet_dir = Path(raw_source)
            if not packet_dir.is_absolute():
                packet_dir = (workspace_root / packet_dir).resolve()
            if not packet_dir.exists():
                print(f"[cpm:build] packet directory not found: {packet_dir}")
                return 1

            invocation = _merge_invocation(argv, workspace_root)
            embedder = EmbeddingClient(
                invocation.config.embed_url,
                mode=invocation.config.embeddings_mode,
                timeout_s=invocation.config.timeout,
            )
            manifest = embed_packet_from_chunks(
                packet_dir,
                model_name=invocation.config.model_name,
                max_seq_length=invocation.config.max_seq_length,
                archive=invocation.config.archive,
                archive_format=invocation.config.archive_format,
                embedder=embedder,
                packet_name_override=_as_str(getattr(argv, "name", None), "").strip() or None,
                packet_version_override=_as_str(getattr(argv, "packet_version", None), "").strip() or None,
                description_override=_as_str(getattr(argv, "description", None), "").strip() or None,
            )
            if manifest is None:
                return 1

            lockfile_name = str(getattr(argv, "lockfile", DEFAULT_LOCKFILE_NAME) or DEFAULT_LOCKFILE_NAME).strip()
            if not lockfile_name:
                lockfile_name = DEFAULT_LOCKFILE_NAME
            lock_path = packet_dir / lockfile_name
            update_lock = bool(getattr(argv, "update_lock", False))
            if lock_path.exists() or update_lock:
                if lock_path.exists():
                    try:
                        lock_payload = load_lock(lock_path)
                    except Exception as exc:
                        print(f"[cpm:build] unable to read lockfile: {exc}")
                        return 1
                else:
                    lock_payload = {
                        "lockfileVersion": 1,
                        "packet": {
                            "name": str(manifest.cpm.get("name") or manifest.packet_id),
                            "version": str(manifest.cpm.get("version") or ""),
                        },
                        "inputs": [],
                        "pipeline": [],
                        "models": [],
                        "artifacts": {},
                        "resolution": {},
                    }
                lock_payload["artifacts"] = artifact_hashes(packet_dir)
                resolution = lock_payload.get("resolution") if isinstance(lock_payload.get("resolution"), dict) else {}
                resolution["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                lock_payload["resolution"] = resolution
                write_lock(lock_path, lock_payload)
                print(f"[cpm:build] lockfile updated: {lock_path}")
            return 0

        invocation = _merge_invocation(argv, workspace_root)
        if not invocation.packet_name:
            print("[cpm:build] --name is required")
            return 1
        if not invocation.packet_version:
            print("[cpm:build] --version (alias: --packet-version) is required")
            return 1

        invocation.destination_root.mkdir(parents=True, exist_ok=True)
        invocation.packet_dir.mkdir(parents=True, exist_ok=True)

        builder_entry = _resolve_builder_entry(invocation.builder, workspace_root)
        if builder_entry is None:
            print(f"[error] builder '{invocation.builder}' not found in registry")
            available = _list_builder_specs(workspace_root)
            if available:
                print(f"[hint] available builders: {', '.join(available)}")
            return 1

        builder_plugin_version = _resolve_builder_plugin_version(builder_entry, workspace_root)
        plan = _build_lock_plan(
            invocation,
            builder_entry=builder_entry,
            builder_plugin_version=builder_plugin_version,
        )

        lockfile_name = str(getattr(argv, "lockfile", DEFAULT_LOCKFILE_NAME) or DEFAULT_LOCKFILE_NAME).strip()
        if not lockfile_name:
            lockfile_name = DEFAULT_LOCKFILE_NAME
        lock_path = invocation.packet_dir / lockfile_name
        frozen_lockfile = bool(getattr(argv, "frozen_lockfile", False))
        update_lock = bool(getattr(argv, "update_lock", False))

        if action == "verify":
            if not lock_path.exists():
                print(f"[cpm:build] lockfile not found: {lock_path}")
                return 1
            try:
                lock_payload = load_lock(lock_path)
            except Exception as exc:
                print(f"[cpm:build] unable to read lockfile: {exc}")
                return 1
            plan_result = verify_lock_against_plan(lock_payload, plan)
            artifacts_result = verify_artifacts(lock_payload, invocation.packet_dir)
            if frozen_lockfile and lock_has_non_deterministic_sections(lock_payload):
                print("[cpm:build] lockfile contains non_deterministic sections and --frozen-lockfile is enabled")
                return 1
            if not plan_result.ok:
                _print_verify_errors(plan_result.errors)
                return 1
            if not artifacts_result.ok:
                _print_verify_errors(artifacts_result.errors)
                return 1
            print(f"[cpm:build] verify ok: {lock_path}")
            return 0

        lock_payload = None
        if lock_path.exists():
            try:
                lock_payload = load_lock(lock_path)
            except Exception as exc:
                print(f"[cpm:build] unable to read lockfile: {exc}")
                return 1
            if not update_lock:
                verify_result = verify_lock_against_plan(lock_payload, plan)
                if not verify_result.ok:
                    print("[cpm:build] lockfile does not match current build inputs/config; use --update-lock")
                    _print_verify_errors(verify_result.errors)
                    return 1
            if frozen_lockfile and lock_has_non_deterministic_sections(lock_payload):
                print("[cpm:build] lockfile contains non_deterministic sections and --frozen-lockfile is enabled")
                return 1
        elif frozen_lockfile:
            print(f"[cpm:build] --frozen-lockfile requires an existing lockfile at {lock_path}")
            return 1

        if action == "lock":
            payload = render_lock(plan, artifacts=artifact_hashes(invocation.packet_dir))
            write_lock(lock_path, payload)
            print(f"[cpm:build] lockfile written: {lock_path}")
            return 0

        if lock_payload is None or update_lock:
            payload = render_lock(plan, artifacts=artifact_hashes(invocation.packet_dir))
            write_lock(lock_path, payload)

        ok = _execute_builder(invocation, builder_entry, argv)
        if not ok:
            return 1

        payload = render_lock(plan, artifacts=artifact_hashes(invocation.packet_dir))
        write_lock(lock_path, payload)
        print(f"[cpm:build] lockfile updated: {lock_path}")
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
