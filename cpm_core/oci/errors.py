"""Typed OCI client errors."""

from __future__ import annotations


class OciError(RuntimeError):
    """Base OCI error."""


class OciCommandError(OciError):
    """ORAS command execution failed."""


class OciAuthError(OciError):
    """Authentication-related issue."""


class OciSecurityError(OciError):
    """Security policy violation (allowlist/tls/path)."""


class OciNotSupportedError(OciError):
    """Operation is not supported by the underlying registry/client."""
