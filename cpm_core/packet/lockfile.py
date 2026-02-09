from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Mapping, Sequence


LOCKFILE_VERSION = 1
DEFAULT_LOCKFILE_NAME = "packet.lock.json"


@dataclass(frozen=True)
class ResolvedPacketPlan:
    packet: dict[str, Any]
    inputs: list[dict[str, Any]]
    pipeline: list[dict[str, Any]]
    models: list[dict[str, Any]]
    warnings: list[str]


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    errors: tuple[str, ...]


def _canonical_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_path(path: Path) -> str:
    return path.as_posix().replace("\\", "/")


def _directory_tree_hash(root: Path) -> str:
    entries: list[tuple[str, str]] = []
    for item in sorted(root.rglob("*")):
        if not item.is_file():
            continue
        rel = _normalize_path(item.relative_to(root))
        entries.append((rel, _sha256_file(item)))
    payload = "\n".join(f"{rel}:{digest}" for rel, digest in entries)
    return _sha256_text(payload)


def _hash_inputs(source_path: Path) -> list[dict[str, Any]]:
    resolved = source_path.resolve()
    if resolved.is_file():
        return [
            {
                "kind": "file",
                "ref": _normalize_path(resolved),
                "hash": _sha256_file(resolved),
            }
        ]
    if resolved.is_dir():
        return [
            {
                "kind": "dir",
                "ref": _normalize_path(resolved),
                "hash": _directory_tree_hash(resolved),
            }
        ]
    return []


def _cpm_version() -> str:
    try:
        return importlib_metadata.version("cpm")
    except Exception:
        return "unknown"


def build_resolved_plan(
    *,
    source_path: Path,
    packet_name: str,
    packet_version: str,
    packet_id: str,
    build_profile: str,
    builder_plugin: str,
    builder_plugin_version: str,
    config_payload: Mapping[str, Any],
    model_provider: str,
    model_name: str,
    model_dtype: str,
    normalize: bool,
    max_seq_length: int | None,
) -> ResolvedPacketPlan:
    config_hash = _sha256_text(_canonical_json(dict(config_payload)))
    warnings: list[str] = []
    pipeline = [
        {
            "step": "build",
            "plugin": builder_plugin,
            "plugin_version": builder_plugin_version,
            "config_hash": config_hash,
            "params": {
                "packet_name": packet_name,
                "packet_version": packet_version,
            },
        },
        {
            "step": "embed",
            "plugin": builder_plugin,
            "plugin_version": builder_plugin_version,
            "config_hash": config_hash,
            "params": {
                "model": model_name,
                "normalize": bool(normalize),
                "max_seq_length": max_seq_length,
            },
        },
        {
            "step": "index",
            "plugin": builder_plugin,
            "plugin_version": builder_plugin_version,
            "config_hash": config_hash,
            "params": {"index": "faiss.IndexFlatIP"},
        },
    ]
    models = [
        {
            "provider": model_provider,
            "model": model_name,
            "revision": None,
            "dtype": model_dtype,
            "device_policy": "runtime-default",
            "normalize": bool(normalize),
            "max_seq_length": max_seq_length,
        }
    ]
    resolved_packet_id = _sha256_text(
        _canonical_json(
            {
                "packet_name": packet_name,
                "packet_version": packet_version,
                "build_profile": build_profile,
                "source": _normalize_path(source_path.resolve()),
                "config_hash": config_hash,
            }
        )
    )
    packet = {
        "name": packet_name,
        "version": packet_version,
        "packet_id": packet_id,
        "resolved_packet_id": resolved_packet_id,
        "build_profile": build_profile,
    }
    return ResolvedPacketPlan(
        packet=packet,
        inputs=_hash_inputs(source_path),
        pipeline=pipeline,
        models=models,
        warnings=warnings,
    )


def render_lock(
    plan: ResolvedPacketPlan,
    *,
    artifacts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "lockfileVersion": LOCKFILE_VERSION,
        "packet": dict(plan.packet),
        "inputs": [dict(item) for item in plan.inputs],
        "pipeline": [dict(item) for item in plan.pipeline],
        "models": [dict(item) for item in plan.models],
        "artifacts": dict(artifacts or {}),
        "resolution": {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "cpm_version": _cpm_version(),
            "warnings": list(plan.warnings),
        },
    }


def write_lock(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def load_lock(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("lockfile payload must be an object")
    return data


def artifact_hashes(packet_dir: Path) -> dict[str, str]:
    targets = {
        "chunks_manifest_hash": packet_dir / "docs.jsonl",
        "embeddings_hash": packet_dir / "vectors.f16.bin",
        "index_hash": packet_dir / "faiss" / "index.faiss",
        "packet_manifest_hash": packet_dir / "manifest.json",
    }
    result: dict[str, str] = {}
    for key, target in targets.items():
        if target.exists():
            result[key] = _sha256_file(target)
    return result


def verify_lock_against_plan(lock_payload: Mapping[str, Any], plan: ResolvedPacketPlan) -> VerifyResult:
    errors: list[str] = []
    if int(lock_payload.get("lockfileVersion") or 0) != LOCKFILE_VERSION:
        errors.append(
            f"lockfileVersion mismatch: expected={LOCKFILE_VERSION} got={lock_payload.get('lockfileVersion')}"
        )

    lock_packet = lock_payload.get("packet")
    if not isinstance(lock_packet, dict):
        errors.append("lock packet section is missing or invalid")
    else:
        for field in ("name", "version", "packet_id", "resolved_packet_id", "build_profile"):
            if lock_packet.get(field) != plan.packet.get(field):
                errors.append(f"packet.{field} mismatch: expected={plan.packet.get(field)!r} got={lock_packet.get(field)!r}")

    lock_inputs = lock_payload.get("inputs")
    if lock_inputs != plan.inputs:
        errors.append("inputs mismatch")

    lock_pipeline = lock_payload.get("pipeline")
    if lock_pipeline != plan.pipeline:
        errors.append("pipeline mismatch")

    lock_models = lock_payload.get("models")
    if lock_models != plan.models:
        errors.append("models mismatch")

    return VerifyResult(ok=not errors, errors=tuple(errors))


def verify_artifacts(lock_payload: Mapping[str, Any], packet_dir: Path) -> VerifyResult:
    errors: list[str] = []
    lock_artifacts = lock_payload.get("artifacts")
    if not isinstance(lock_artifacts, dict):
        return VerifyResult(ok=True, errors=())

    actual = artifact_hashes(packet_dir)
    for key, expected in lock_artifacts.items():
        if key not in actual:
            errors.append(f"artifact missing: {key}")
            continue
        if actual[key] != expected:
            errors.append(f"artifact hash mismatch for {key}: expected={expected} got={actual[key]}")
    return VerifyResult(ok=not errors, errors=tuple(errors))


def lock_has_non_deterministic_sections(lock_payload: Mapping[str, Any]) -> bool:
    pipeline = lock_payload.get("pipeline")
    if isinstance(pipeline, Sequence):
        for step in pipeline:
            if isinstance(step, Mapping) and bool(step.get("non_deterministic")):
                return True
    models = lock_payload.get("models")
    if isinstance(models, Sequence):
        for model in models:
            if isinstance(model, Mapping) and bool(model.get("non_deterministic")):
                return True
    return False
