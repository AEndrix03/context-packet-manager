"""OCI client wrapper built on top of ORAS CLI."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from .errors import OciCommandError, OciNotSupportedError
from .security import assert_allowlisted, redact_command_for_log
from .types import OciArtifactSpec, OciClientConfig, OciPullResult, OciPushResult, OciReferrer

logger = logging.getLogger(__name__)
_DIGEST_RE = re.compile(r"sha256:[a-f0-9]{64}")


class OciClient:
    """Thin ORAS CLI wrapper with retries and security checks."""

    def __init__(self, config: OciClientConfig | None = None) -> None:
        self.config = config or OciClientConfig()

    def resolve(self, ref: str) -> str:
        assert_allowlisted(ref, self.config.allowlist_domains)
        command = ["oras", "resolve", ref]
        result = self._run(command)
        digest = _extract_digest(result.stdout) or _extract_digest(result.stderr)
        if not digest:
            raise OciCommandError(f"unable to resolve digest for ref '{ref}'")
        return digest

    def list_tags(self, ref: str) -> list[str]:
        assert_allowlisted(ref, self.config.allowlist_domains)
        command = ["oras", "repo", "tags", ref]
        result = self._run(command, fail_on_last=True)
        text = (result.stdout or "").strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines:
                raise OciNotSupportedError("oras repo tags returned no tags")
            return lines
        if isinstance(payload, dict):
            tags = payload.get("tags")
            if isinstance(tags, list):
                return [str(tag) for tag in tags]
        if isinstance(payload, list):
            return [str(tag) for tag in payload]
        raise OciNotSupportedError("unable to parse tags output")

    def pull(self, ref_or_digest: str, output_dir: Path) -> OciPullResult:
        assert_allowlisted(ref_or_digest, self.config.allowlist_domains)
        output_dir.mkdir(parents=True, exist_ok=True)
        command = ["oras", "pull", ref_or_digest, "-o", str(output_dir)]
        result = self._run(command)
        files = tuple(path for path in output_dir.rglob("*") if path.is_file())
        self._enforce_size_limit(files)
        digest = _extract_digest(result.stdout) or _extract_digest(result.stderr)
        return OciPullResult(ref=ref_or_digest, digest=digest, files=files)

    def fetch_manifest(self, ref_or_digest: str) -> dict[str, Any]:
        assert_allowlisted(ref_or_digest, self.config.allowlist_domains)
        result = self._run(["oras", "manifest", "fetch", ref_or_digest])
        payload = _parse_json_document(result.stdout)
        if not isinstance(payload, dict):
            raise OciCommandError("unable to parse OCI manifest payload")
        return payload

    def fetch_blob(self, ref_or_digest: str, digest: str) -> bytes:
        assert_allowlisted(ref_or_digest, self.config.allowlist_domains)
        if not digest:
            raise OciCommandError("missing blob digest")
        command = ["oras", "blob", "fetch", ref_or_digest, digest]
        try:
            result = self._run(command)
            return (result.stdout or "").encode("utf-8")
        except OciCommandError:
            # ORAS v1.3+ expects a single positional argument in the form <name>@<digest>.
            combined_ref = f"{ref_or_digest}@{digest}"
            fallback_command = ["oras", "blob", "fetch", combined_ref]
            try:
                fallback = self._run(fallback_command)
                return (fallback.stdout or "").encode("utf-8")
            except OciCommandError:
                # Some ORAS builds require writing blob payload to file.
                with tempfile.TemporaryDirectory(prefix="cpm-oci-blob-") as tmp:
                    output_path = Path(tmp) / "blob.bin"
                    output_command = ["oras", "blob", "fetch", "--output", str(output_path), combined_ref]
                    self._run(output_command)
                    return output_path.read_bytes()

    def discover_referrers(self, ref_or_digest: str) -> list[OciReferrer]:
        assert_allowlisted(ref_or_digest, self.config.allowlist_domains)
        command = ["oras", "discover", ref_or_digest, "--output", "json"]
        try:
            result = self._run(command)
        except OciCommandError:
            return self._discover_referrers_from_tags(ref_or_digest)

        parsed = _parse_referrers_payload((result.stdout or "").strip())
        if parsed:
            return parsed
        return self._discover_referrers_from_tags(ref_or_digest)

    def push(self, ref: str, artifact: OciArtifactSpec) -> OciPushResult:
        assert_allowlisted(ref, self.config.allowlist_domains)
        if not artifact.files:
            raise OciCommandError("artifact spec has no files to publish")
        files = [path.resolve() for path in artifact.files]
        common_root = Path(os.path.commonpath([str(path.parent) for path in files]))
        command = ["oras", "push", ref]
        for path in files:
            rel_path = path.relative_to(common_root)
            path_arg = rel_path.as_posix()
            media = artifact.media_types.get(path.name) or artifact.media_types.get(str(path))
            if media:
                command.append(f"{path_arg}:{media}")
            else:
                command.append(path_arg)
        result = self._run(command, cwd=common_root)
        digest = _extract_digest(result.stdout) or _extract_digest(result.stderr)
        if not digest:
            digest = self.resolve(ref)
        return OciPushResult(ref=ref, digest=digest)

    def _discover_referrers_from_tags(self, ref_or_digest: str) -> list[OciReferrer]:
        repository = _repository_for_tags(ref_or_digest)
        try:
            tags = self.list_tags(repository)
        except OciCommandError:
            return []
        results: list[OciReferrer] = []
        for tag in tags:
            lowered = tag.lower()
            if lowered.endswith(".sig") or "cosign" in lowered:
                results.append(
                    OciReferrer(
                        digest=f"tag:{tag}",
                        artifact_type="application/vnd.dev.cosign.simulated.v1+json",
                        annotations={"tag": tag},
                        source="referrers-tag",
                    )
                )
            elif lowered.endswith(".sbom") or "sbom" in lowered or "spdx" in lowered or "cyclonedx" in lowered:
                results.append(
                    OciReferrer(
                        digest=f"tag:{tag}",
                        artifact_type="application/vnd.cpm.sbom.simulated.v1+json",
                        annotations={"tag": tag},
                        source="referrers-tag",
                    )
                )
            elif lowered.endswith(".prov") or "provenance" in lowered or "slsa" in lowered:
                results.append(
                    OciReferrer(
                        digest=f"tag:{tag}",
                        artifact_type="application/vnd.cpm.provenance.simulated.v1+json",
                        annotations={"tag": tag},
                        source="referrers-tag",
                    )
                )
        return results

    def _run(
        self,
        command: list[str],
        *,
        fail_on_last: bool = True,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        base_redacted = " ".join(redact_command_for_log(command))
        if self.config.insecure:
            command = [*command, "--insecure"]
        if self.config.plain_http:
            command = [*command, "--plain-http"]
        if self.config.username and self.config.password:
            command = [*command, "--username", self.config.username, "--password", self.config.password]
        elif self.config.token:
            command = [*command, "--token", self.config.token]

        timeout = max(float(self.config.timeout_seconds), 1.0)
        retries = max(int(self.config.max_retries), 1)
        backoff = max(float(self.config.backoff_seconds), 0.0)

        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                redacted = " ".join(redact_command_for_log(command))
                logger.debug("oci command attempt=%s/%s cmd=%s", attempt, retries, redacted)
                started = time.monotonic()
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=str(cwd) if cwd is not None else None,
                )
                elapsed_ms = int((time.monotonic() - started) * 1000)
                logger.debug(
                    "oci command done attempt=%s/%s exit=%s elapsed_ms=%s cmd=%s",
                    attempt,
                    retries,
                    result.returncode,
                    elapsed_ms,
                    redacted,
                )
                if result.returncode == 0:
                    return result
                if attempt >= retries and fail_on_last:
                    raise OciCommandError(_format_failure(command, result.returncode, result.stderr))
            except FileNotFoundError as exc:
                raise OciCommandError(
                    "oras CLI not found. Install ORAS and ensure it is available in PATH."
                ) from exc
            except subprocess.TimeoutExpired as exc:
                last_error = exc
                if attempt >= retries:
                    raise OciCommandError(
                        f"oras command timed out after {timeout:.1f}s (attempt={attempt}/{retries}, cmd='{base_redacted}')"
                    ) from exc
            if attempt < retries:
                time.sleep(min(backoff * attempt, 2.0))
        if isinstance(last_error, Exception):
            raise OciCommandError("oras command failed after retries") from last_error
        raise OciCommandError("oras command failed")

    def _enforce_size_limit(self, files: tuple[Path, ...]) -> None:
        limit = self.config.max_artifact_size_bytes
        if limit is None:
            return
        total = sum(path.stat().st_size for path in files)
        if total > limit:
            raise OciCommandError(
                f"artifact size {total} exceeds configured limit {limit} bytes"
            )


def build_artifact_spec(
    files: list[Path],
    media_types: Mapping[str, str] | None = None,
) -> OciArtifactSpec:
    return OciArtifactSpec(files=tuple(files), media_types=dict(media_types or {}))


def _extract_digest(text: str | None) -> str | None:
    if not text:
        return None
    match = _DIGEST_RE.search(text)
    if not match:
        return None
    return match.group(0)


def _format_failure(command: list[str], code: int, stderr: str | None) -> str:
    redacted = " ".join(redact_command_for_log(command))
    detail = (stderr or "").strip()
    if detail:
        return f"oras command failed (exit={code}) cmd='{redacted}' err='{detail}'"
    return f"oras command failed (exit={code}) cmd='{redacted}'"


def _parse_referrers_payload(payload: str) -> list[OciReferrer]:
    if not payload:
        return []
    try:
        document = json.loads(payload)
    except json.JSONDecodeError:
        return []
    manifests = None
    if isinstance(document, dict):
        if isinstance(document.get("manifests"), list):
            manifests = document.get("manifests")
        elif isinstance(document.get("referrers"), list):
            manifests = document.get("referrers")
    elif isinstance(document, list):
        manifests = document
    if not isinstance(manifests, list):
        return []

    results: list[OciReferrer] = []
    for item in manifests:
        if not isinstance(item, dict):
            continue
        digest = str(item.get("digest") or "").strip()
        artifact_type = str(item.get("artifactType") or item.get("mediaType") or "").strip()
        annotations = item.get("annotations")
        safe_annotations = (
            {str(key): str(value) for key, value in annotations.items()}
            if isinstance(annotations, dict)
            else {}
        )
        if not digest or not artifact_type:
            continue
        results.append(
            OciReferrer(
                digest=digest,
                artifact_type=artifact_type,
                annotations=safe_annotations,
            )
        )
    return results


def _parse_json_document(payload: str | None) -> Any:
    text = (payload or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise OciCommandError("invalid JSON payload from oras command") from exc


def _repository_for_tags(ref_or_digest: str) -> str:
    value = ref_or_digest.strip()
    if "@" in value:
        return value.split("@", 1)[0]
    slash_index = value.rfind("/")
    colon_index = value.rfind(":")
    if colon_index > slash_index:
        return value[:colon_index]
    return value
