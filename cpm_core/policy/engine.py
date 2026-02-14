from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PolicyModel:
    mode: str = "strict"
    allowed_sources: tuple[str, ...] = ()
    min_trust_score: float = 0.0
    max_tokens: int = 6000


@dataclass(frozen=True)
class PolicyDecision:
    allow: bool
    decision: str
    reason: str
    warnings: tuple[str, ...] = ()


def load_policy(workspace_root: Path) -> PolicyModel:
    policy_path = workspace_root / "policy.yml"
    if not policy_path.exists():
        return PolicyModel()
    try:
        raw = _parse_policy_yaml(policy_path.read_text(encoding="utf-8"))
    except Exception:
        return PolicyModel()
    allowed = raw.get("allowed_sources")
    allowed_sources = tuple(str(item) for item in (allowed if isinstance(allowed, list) else []) if str(item).strip())
    return PolicyModel(
        mode=str(raw.get("mode", "strict")).strip().lower() or "strict",
        allowed_sources=allowed_sources,
        min_trust_score=float(raw.get("min_trust_score", 0.0)),
        max_tokens=int(raw.get("max_tokens", 6000)),
    )


def evaluate_policy(
    policy: PolicyModel,
    *,
    source_uri: str | None = None,
    trust_score: float | None = None,
    token_count: int | None = None,
    strict_failures: list[str] | None = None,
) -> PolicyDecision:
    warnings: list[str] = []
    if source_uri and policy.allowed_sources:
        if not any(_source_matches(pattern, source_uri) for pattern in policy.allowed_sources):
            return PolicyDecision(allow=False, decision="deny", reason="source_not_allowlisted")
    if trust_score is not None and trust_score < policy.min_trust_score:
        return PolicyDecision(allow=False, decision="deny", reason="trust_score_below_threshold")
    if token_count is not None and token_count > policy.max_tokens:
        return PolicyDecision(allow=False, decision="deny", reason="token_budget_exceeded")
    if strict_failures:
        if policy.mode == "strict":
            return PolicyDecision(allow=False, decision="deny", reason="strict_verification_failed")
        warnings.append("strict_failures_ignored")
    if warnings:
        return PolicyDecision(allow=True, decision="warn", reason="policy_warning", warnings=tuple(warnings))
    return PolicyDecision(allow=True, decision="allow", reason="ok")


def _parse_policy_yaml(content: str) -> dict[str, object]:
    data: dict[str, object] = {}
    section: str | None = None
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1].strip().lower()
            continue
        if section not in {None, "policy"}:
            continue
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            existing = data.setdefault("allowed_sources", [])
            if isinstance(existing, list):
                existing.append(value)
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        parsed_key = key.strip()
        if parsed_key == "allowed_sources" and not value.strip():
            data[parsed_key] = []
            continue
        data[parsed_key] = _coerce_yaml_value(value.strip())
    return data


def _coerce_yaml_value(value: str) -> object:
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    if lower in {"null", "none", "~", ""}:
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip("\"'")


def _source_matches(pattern: str, value: str) -> bool:
    if pattern.endswith("*"):
        return value.startswith(pattern[:-1])
    return value == pattern
