from __future__ import annotations

import json
import tempfile
import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol

from cpm_core.oci import OciClient, OciClientConfig
from cpm_core.oci.packet_metadata import validate_packet_metadata
from cpm_core.oci.packaging import CPM_MANIFEST_MEDIATYPE
from cpm_core.oci.security import evaluate_trust_report

from .cache import SourceCache
from .models import LocalPacket, PacketReference, UpdateInfo


class CPMSource(Protocol):
    def can_handle(self, uri: str) -> bool: ...

    def resolve(self, uri: str) -> PacketReference: ...

    def inspect_metadata(self, uri: str, cache: SourceCache) -> tuple[PacketReference, dict[str, Any]]: ...

    def fetch(self, ref: PacketReference, cache: SourceCache) -> LocalPacket: ...

    def check_updates(self, ref: PacketReference) -> UpdateInfo: ...


def _load_oci_config(workspace_root: Path) -> dict[str, object]:
    config_path = workspace_root / "config" / "config.toml"
    if not config_path.exists():
        return {}
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    section = payload.get("oci")
    return section if isinstance(section, dict) else {}


class OciSource:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    def can_handle(self, uri: str) -> bool:
        return uri.startswith("oci://")

    def _client(self) -> OciClient:
        config = _load_oci_config(self.workspace_root)
        # Resolver calls back MCP lookup/query and should fail fast on network issues.
        timeout_seconds = float(config.get("timeout_seconds", 10.0))
        max_retries = int(config.get("max_retries", 1))
        return OciClient(
            OciClientConfig(
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                backoff_seconds=float(config.get("backoff_seconds", 0.2)),
                insecure=bool(config.get("insecure", False)),
                plain_http=bool(config.get("plain_http", False)),
                allowlist_domains=tuple(str(item) for item in config.get("allowlist_domains", []) if str(item).strip()),
                max_artifact_size_bytes=(
                    int(config["max_artifact_size_bytes"])
                    if config.get("max_artifact_size_bytes") is not None
                    else None
                ),
                username=str(config.get("username") or "").strip() or None,
                password=str(config.get("password") or "").strip() or None,
                token=str(config.get("token") or "").strip() or None,
            )
        )

    @staticmethod
    def _to_ref(uri: str) -> str:
        raw = uri[len("oci://") :].strip("/")
        if not raw:
            raise ValueError("invalid OCI source URI")
        if "@sha256:" in raw:
            return raw
        if "@" in raw:
            name, version = raw.split("@", 1)
            if not version:
                raise ValueError("invalid OCI source URI: missing version")
            return f"{name}:{version}"
        slash_index = raw.rfind("/")
        colon_index = raw.rfind(":")
        if colon_index <= slash_index:
            return f"{raw}:latest"
        return raw

    def _verify(self, client: OciClient, ref: str, digest: str) -> dict[str, Any]:
        verification_cfg = _load_oci_config(self.workspace_root)
        strict = bool(verification_cfg.get("strict_verify", True))
        report = evaluate_trust_report(
            client.discover_referrers(f"{ref.split('@', 1)[0]}@{digest}"),
            strict=strict,
            require_signature=bool(verification_cfg.get("require_signature", True)),
            require_sbom=bool(verification_cfg.get("require_sbom", True)),
            require_provenance=bool(verification_cfg.get("require_provenance", True)),
        )
        if strict and report.strict_failures:
            failures = ",".join(report.strict_failures)
            raise ValueError(f"OCI source verification failed: {failures}")
        return {"trust_score": report.trust_score, "verification": asdict(report)}

    def resolve(self, uri: str) -> PacketReference:
        ref = self._to_ref(uri)
        client = self._client()
        digest = client.resolve(ref)
        verification = self._verify(client, ref, digest)
        return PacketReference(
            uri=uri,
            resolved_uri=f"oci://{ref}",
            digest=digest,
            metadata={
                "source": "oci",
                "ref": ref,
                **verification,
            },
        )

    def inspect_metadata(self, uri: str, cache: SourceCache) -> tuple[PacketReference, dict[str, Any]]:
        ref = self._to_ref(uri)
        client = self._client()
        digest = client.resolve(ref)
        cached = cache.read_metadata(digest=digest)
        if cached is not None:
            metadata_payload = cached
            metadata_digest = str(cached.get("_metadata_digest") or "")
        else:
            manifest = client.fetch_manifest(ref)
            metadata_digest = _select_metadata_digest(manifest)
            if metadata_digest:
                blob = client.fetch_blob(ref, metadata_digest)
                parsed = json.loads(blob.decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise ValueError("invalid packet metadata payload")
                metadata_payload = _normalize_metadata_payload(parsed)
            else:
                metadata_payload = self._read_legacy_metadata(client, ref)
                metadata_digest = ""
            metadata_payload["_metadata_digest"] = metadata_digest
            cache.write_metadata(digest=digest, payload=metadata_payload)
        verification = self._verify(client, ref, digest)
        reference = PacketReference(
            uri=uri,
            resolved_uri=f"oci://{ref}",
            digest=digest,
            metadata={
                "source": "oci",
                "ref": ref,
                "metadata_digest": metadata_digest,
                **verification,
            },
        )
        return reference, metadata_payload

    def _read_legacy_metadata(self, client: OciClient, ref: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="cpm-source-oci-legacy-") as tmp:
            pull_dir = Path(tmp) / "artifact"
            client.pull(ref, pull_dir)
            manifest_path = pull_dir / "packet.manifest.json"
            if manifest_path.exists():
                try:
                    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                except Exception:
                    payload = {}
                if isinstance(payload, dict):
                    return _normalize_metadata_payload(payload)
            payload_root = "payload"
            cpm_path = pull_dir / payload_root / "cpm.yml"
            packet_name = "unknown"
            packet_version = "unknown"
            if cpm_path.exists():
                for line in cpm_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("name:"):
                        packet_name = line.split(":", 1)[1].strip()
                    elif line.startswith("version:"):
                        packet_version = line.split(":", 1)[1].strip()
            fallback = {
                "schema": "cpm.packet.metadata",
                "schema_version": "1.0",
                "packet": {"name": packet_name, "version": packet_version},
                "payload": {"files": []},
            }
            validate_packet_metadata(fallback)
            return fallback

    def fetch(self, ref: PacketReference, cache: SourceCache) -> LocalPacket:
        client = self._client()
        with tempfile.TemporaryDirectory(prefix="cpm-source-oci-") as tmp:
            pull_dir = Path(tmp) / "artifact"
            client.pull(str(ref.metadata.get("ref") or ref.resolved_uri[len("oci://") :]), pull_dir)
            manifest_path = pull_dir / "packet.manifest.json"
            payload_root = "payload"
            if manifest_path.exists():
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                payload_root = str(payload.get("payload_root") or "payload").strip() or "payload"
            payload_dir = pull_dir / payload_root
            if not payload_dir.exists() or not payload_dir.is_dir():
                raise FileNotFoundError(f"OCI payload directory not found: {payload_dir}")
            return cache.materialize_directory(payload_dir, digest=ref.digest)

    def check_updates(self, ref: PacketReference) -> UpdateInfo:
        latest = self._client().resolve(str(ref.metadata.get("ref") or ref.resolved_uri[len("oci://") :]))
        return UpdateInfo(has_update=latest != ref.digest, latest_digest=latest)


class SourceResolver:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self.cache = SourceCache(self.workspace_root)
        self._source: CPMSource = OciSource(self.workspace_root)

    def resolve_and_fetch(self, uri: str) -> tuple[PacketReference, LocalPacket]:
        if not self._source.can_handle(uri):
            raise ValueError("unsupported source URI: only oci:// is supported")
        reference = self._source.resolve(uri)
        packet = self._source.fetch(reference, self.cache)
        return reference, packet

    def lookup_metadata(self, uri: str) -> tuple[PacketReference, dict[str, Any]]:
        if not self._source.can_handle(uri):
            raise ValueError("unsupported source URI: only oci:// is supported")
        return self._source.inspect_metadata(uri, self.cache)


def _select_metadata_digest(manifest_payload: dict[str, Any]) -> str | None:
    layers = manifest_payload.get("layers")
    if not isinstance(layers, list):
        return None
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        media_type = str(layer.get("mediaType") or "").strip()
        if media_type != CPM_MANIFEST_MEDIATYPE:
            continue
        digest = str(layer.get("digest") or "").strip()
        if digest:
            return digest
    return None


def _normalize_metadata_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") == "cpm-oci/v1":
        packet = payload.get("packet") if isinstance(payload.get("packet"), dict) else {}
        normalized = {
            "schema": "cpm.packet.metadata",
            "schema_version": "1.0",
            "packet": {
                "name": str(packet.get("name") or ""),
                "version": str(packet.get("version") or ""),
            },
            "payload": {"files": []},
            "payload_root": str(payload.get("payload_root") or "payload"),
        }
        source_manifest = payload.get("source_manifest")
        if isinstance(source_manifest, dict):
            normalized["source_manifest"] = source_manifest
        validate_packet_metadata(normalized)
        return normalized
    validate_packet_metadata(payload)
    return payload
