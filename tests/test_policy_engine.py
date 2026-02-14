from __future__ import annotations

from pathlib import Path

from cpm_core.policy import evaluate_policy, load_policy
from cpm_core.policy.engine import PolicyModel

EXPECTED_MIN_TRUST = 0.8
EXPECTED_MAX_TOKENS = 1234


def test_policy_loads_allowlist_and_threshold(tmp_path: Path) -> None:
    root = tmp_path / ".cpm"
    root.mkdir(parents=True, exist_ok=True)
    (root / "policy.yml").write_text(
        "\n".join(
            [
                "policy:",
                "  mode: strict",
                "  min_trust_score: 0.8",
                "  max_tokens: 1234",
                "  allowed_sources:",
                "    - oci://registry.local/*",
            ]
        ),
        encoding="utf-8",
    )
    policy = load_policy(root)
    assert policy.mode == "strict"
    assert policy.min_trust_score == EXPECTED_MIN_TRUST
    assert policy.max_tokens == EXPECTED_MAX_TOKENS
    assert policy.allowed_sources == ("oci://registry.local/*",)


def test_policy_denies_non_allowlisted_source() -> None:
    policy = PolicyModel(mode="strict", allowed_sources=("oci://registry.local/*",))
    result = evaluate_policy(policy, source_uri="oci://other.local/team/pkg")
    assert result.allow is False
    assert result.reason == "source_not_allowlisted"
