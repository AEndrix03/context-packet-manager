"""OCI client wrapper built on top of ORAS CLI."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Mapping

from .errors import OciCommandError, OciNotSupportedError
from .security import assert_allowlisted, redact_command_for_log
from .types import OciArtifactSpec, OciClientConfig, OciPullResult, OciPushResult

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

    def push(self, ref: str, artifact: OciArtifactSpec) -> OciPushResult:
        assert_allowlisted(ref, self.config.allowlist_domains)
        command = ["oras", "push", ref]
        for path in artifact.files:
            media = artifact.media_types.get(path.name) or artifact.media_types.get(str(path))
            if media:
                command.append(f"{path}:{media}")
            else:
                command.append(str(path))
        result = self._run(command)
        digest = _extract_digest(result.stdout) or _extract_digest(result.stderr)
        if not digest:
            digest = self.resolve(ref)
        return OciPushResult(ref=ref, digest=digest)

    def _run(self, command: list[str], *, fail_on_last: bool = True) -> subprocess.CompletedProcess[str]:
        if self.config.insecure:
            command = [*command, "--insecure"]
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
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
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
                    raise OciCommandError(f"oras command timed out after {timeout:.1f}s") from exc
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
