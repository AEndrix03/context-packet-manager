from __future__ import annotations

import json
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HubSettings:
    base_url: str | None
    enforce_remote_policy: bool = False
    timeout_seconds: float = 5.0


def load_hub_settings(workspace_root: Path) -> HubSettings:
    config_path = workspace_root / "config" / "config.toml"
    if not config_path.exists():
        return HubSettings(base_url=None)
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return HubSettings(base_url=None)
    hub = payload.get("hub")
    if not isinstance(hub, dict):
        return HubSettings(base_url=None)
    base_url = str(hub.get("url") or "").strip() or None
    return HubSettings(
        base_url=base_url,
        enforce_remote_policy=bool(hub.get("enforce_remote_policy", False)),
        timeout_seconds=float(hub.get("timeout_seconds", 5.0)),
    )


class HubClient:
    def __init__(self, settings: HubSettings) -> None:
        self.settings = settings

    def evaluate_policy(self, context: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any] | None:
        if not self.settings.base_url:
            return None
        endpoint = urllib.parse.urljoin(self.settings.base_url.rstrip("/") + "/", "v1/policy/evaluate")
        body = json.dumps({"context": context, "policy": policy}).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        payload: str | None = None
        try:
            with urllib.request.urlopen(request, timeout=max(self.settings.timeout_seconds, 1.0)) as response:  # nosec - config-driven
                payload = response.read().decode("utf-8")
        except urllib.error.URLError:
            return self._deny_or_none("hub_unreachable")
        if payload is None:
            return self._deny_or_none("hub_invalid_response")
        try:
            result = json.loads(payload)
        except json.JSONDecodeError:
            return self._deny_or_none("hub_invalid_response")
        if not isinstance(result, dict):
            return self._deny_or_none("hub_invalid_response")
        return result

    def _deny_or_none(self, reason: str) -> dict[str, Any] | None:
        if not self.settings.enforce_remote_policy:
            return None
        return {"allow": False, "decision": "deny", "reason": reason}
