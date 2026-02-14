"""Builtin OCI-backed install command."""

from __future__ import annotations

import fnmatch
from argparse import ArgumentParser
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import tempfile
import time
import tomllib
from typing import Any, Iterable

from cpm_builtin.embeddings import EmbeddingsConfigService
from cpm_builtin.packages import PackageManager, parse_package_spec
from cpm_core.api import cpmcommand
from cpm_core.oci import OciClient, OciClientConfig, write_install_lock
from cpm_core.oci.packaging import package_ref_for
from cpm_core.oci.security import evaluate_trust_report
from cpm_core.policy import evaluate_policy, load_policy

from .commands import _WorkspaceAwareCommand


@cpmcommand(name="install", group="cpm")
class InstallCommand(_WorkspaceAwareCommand):
    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("spec", help="Packet spec in the form name@version")
        parser.add_argument("--workspace-dir", default=".", help="Workspace root directory")
        parser.add_argument("--registry", help="OCI registry repository, e.g. harbor.local/project")
        parser.add_argument("--model", help="Override selected embedding model")
        parser.add_argument("--provider", help="Preferred embedding provider name")
        parser.add_argument("--insecure", action="store_true", help="Allow insecure TLS for OCI operations")
        parser.add_argument("--force-discovery", action="store_true", help="Force provider discovery refresh")
        parser.add_argument("--no-embed", action="store_true", help="Install packet without vectors/faiss artifacts")

    def run(self, argv: Any) -> int:
        workspace_root = self._resolve(getattr(argv, "workspace_dir", None))
        policy = load_policy(workspace_root)
        name, version = parse_package_spec(str(argv.spec))
        if not version:
            print("[cpm:install] version is required (use name@version)")
            return 1

        config = _load_oci_config(workspace_root)
        repository = str(getattr(argv, "registry", "") or config.get("repository") or "").strip()
        if not repository:
            print("[cpm:install] missing OCI repository. Set --registry or [oci].repository in config.toml")
            return 1

        client = OciClient(
            OciClientConfig(
                timeout_seconds=float(config.get("timeout_seconds", 30.0)),
                max_retries=int(config.get("max_retries", 2)),
                backoff_seconds=float(config.get("backoff_seconds", 0.2)),
                insecure=bool(getattr(argv, "insecure", False) or config.get("insecure", False)),
                allowlist_domains=tuple(str(item) for item in config.get("allowlist_domains", []) if str(item).strip()),
                max_artifact_size_bytes=(
                    int(config["max_artifact_size_bytes"]) if config.get("max_artifact_size_bytes") is not None else None
                ),
                username=_string_or_none(config.get("username")),
                password=_string_or_none(config.get("password")),
                token=_string_or_none(config.get("token")),
            )
        )

        ref = package_ref_for(name=name, version=version, repository=repository)
        policy_decision = evaluate_policy(policy, source_uri=f"oci://{ref}")
        if not policy_decision.allow:
            print(f"[cpm:install] policy deny source=oci://{ref} reason={policy_decision.reason}")
            return 1
        digest = client.resolve(ref)
        verification = evaluate_trust_report(
            client.discover_referrers(f"{ref.split('@', 1)[0]}@{digest}"),
            strict=bool(config.get("strict_verify", True)),
            require_signature=bool(config.get("require_signature", True)),
            require_sbom=bool(config.get("require_sbom", True)),
            require_provenance=bool(config.get("require_provenance", True)),
        )
        if verification.strict_failures:
            print(
                "[cpm:install] verification failed "
                f"(strict): {','.join(verification.strict_failures)}"
            )
            return 1
        trust_decision = evaluate_policy(
            policy,
            source_uri=f"oci://{ref}",
            trust_score=verification.trust_score,
            strict_failures=list(verification.strict_failures),
        )
        if not trust_decision.allow:
            print(f"[cpm:install] policy deny source=oci://{ref} reason={trust_decision.reason}")
            return 1
        no_embed = bool(getattr(argv, "no_embed", False))

        with tempfile.TemporaryDirectory(prefix=f"cpm-install-{name}-") as tmp:
            pull_dir = Path(tmp) / "artifact"
            pull_result = client.pull(ref, pull_dir)
            manifest_path = pull_dir / "packet.manifest.json"
            if not manifest_path.exists():
                print("[cpm:install] pulled OCI artifact does not contain packet.manifest.json")
                return 1
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload_root = str(payload.get("payload_root") or "payload")
            packet_payload_dir = pull_dir / payload_root
            if not packet_payload_dir.exists():
                print(f"[cpm:install] payload directory not found in artifact: {packet_payload_dir}")
                return 1

            target_dir = workspace_root / "packages" / name / version
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(packet_payload_dir, target_dir)

            if no_embed:
                vectors_path = target_dir / "vectors.f16.bin"
                if vectors_path.exists():
                    vectors_path.unlink()
                faiss_dir = target_dir / "faiss"
                if faiss_dir.exists():
                    shutil.rmtree(faiss_dir)

            selected_model = None
            selected_provider = None
            suggested_retriever = None
            model_artifact = None
            if not no_embed:
                source_manifest = payload.get("source_manifest") if isinstance(payload.get("source_manifest"), dict) else {}
                selection = _select_model(
                    workspace_root=workspace_root,
                    manifest=source_manifest,
                    requested_model=_string_or_none(getattr(argv, "model", None)),
                    requested_provider=_string_or_none(getattr(argv, "provider", None)),
                    force_discovery=bool(getattr(argv, "force_discovery", False)),
                )
                if not selection["model"]:
                    print("[cpm:install] unable to resolve embedding model for this packet")
                    return 1
                selected_model = selection["model"]
                selected_provider = selection["provider"]
                suggested_retriever = selection.get("suggested_retriever")
                model_artifact = _maybe_pull_model_artifact(
                    workspace_root=workspace_root,
                    client=client,
                    provider_name=selected_provider,
                    model_name=selected_model,
                )

            manager = PackageManager(workspace_root)
            manager.use(f"{name}@{version}")

            lock_payload: dict[str, Any] = {
                "name": name,
                "version": version,
                "packet_ref": ref,
                "packet_digest": digest,
                "sources": [
                    {
                        "uri": f"oci://{ref}",
                        "digest": digest,
                        "signature": verification.signature_valid,
                        "sbom": verification.sbom_present,
                        "provenance": verification.provenance_present,
                        "slsa_level": verification.slsa_level,
                        "trust_score": verification.trust_score,
                        "policy": "strict",
                    }
                ],
                "signature": verification.signature_valid,
                "sbom": verification.sbom_present,
                "provenance": verification.provenance_present,
                "trust_score": verification.trust_score,
                "verification": asdict(verification),
                "selected_model": selected_model,
                "selected_provider": selected_provider,
                "suggested_retriever": suggested_retriever,
                "installed_at": int(time.time()),
                "artifact_files": [str(path) for path in pull_result.files],
                "no_embed": no_embed,
            }
            if model_artifact:
                lock_payload["model_artifact"] = model_artifact
            lock_path = write_install_lock(workspace_root, name, lock_payload)
            print(f"[cpm:install] installed {name}@{version} digest={digest}")
            if no_embed:
                print("[cpm:install] mode=no-embed (vectors/faiss removed)")
            else:
                print(f"[cpm:install] selected model={selected_model} provider={selected_provider}")
            print(f"[cpm:install] lock={lock_path}")
        return 0


def _load_oci_config(workspace_root: Path) -> dict[str, Any]:
    config_path = workspace_root / "config" / "config.toml"
    if not config_path.exists():
        return {}
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    section = payload.get("oci")
    return section if isinstance(section, dict) else {}


def _manifest_field(manifest: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in manifest:
        return manifest.get(key)
    extras = manifest.get("extras")
    if isinstance(extras, dict) and key in extras:
        return extras.get(key)
    return default


def _normalize_supported_models(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def _select_model(
    *,
    workspace_root: Path,
    manifest: dict[str, Any],
    requested_model: str | None,
    requested_provider: str | None,
    force_discovery: bool,
) -> dict[str, Any]:
    supported = _normalize_supported_models(_manifest_field(manifest, "supported_models", []))
    recommended = _string_or_none(_manifest_field(manifest, "recommended_model"))
    suggested_retriever = _string_or_none(_manifest_field(manifest, "suggested_retriever"))
    service = EmbeddingsConfigService(workspace_root)
    providers = service.list_providers()
    if requested_provider:
        providers = [service.get_provider(requested_provider)]
    discovery = service.refresh_discovery(force=force_discovery)

    if requested_model:
        provider_name = _find_provider_for_model(providers, discovery, requested_model)
        return {
            "model": requested_model,
            "provider": provider_name,
            "suggested_retriever": suggested_retriever,
        }
    if recommended:
        provider_name = _find_provider_for_model(providers, discovery, recommended)
        return {
            "model": recommended,
            "provider": provider_name,
            "suggested_retriever": suggested_retriever,
        }
    for provider in providers:
        entry = discovery.get(provider.name) if isinstance(discovery.get(provider.name), dict) else {}
        candidates = entry.get("models") if isinstance(entry.get("models"), list) else []
        if not candidates and provider.model:
            candidates = [provider.model]
        for model_name in [str(item) for item in candidates]:
            if not supported or _matches_supported(model_name, supported):
                return {
                    "model": model_name,
                    "provider": provider.name,
                    "suggested_retriever": suggested_retriever,
                }
    return {
        "model": None,
        "provider": providers[0].name if providers else None,
        "suggested_retriever": suggested_retriever,
    }


def _matches_supported(model_name: str, supported: Iterable[str]) -> bool:
    for pattern in supported:
        if fnmatch.fnmatchcase(model_name, pattern):
            return True
    return False


def _find_provider_for_model(providers: list[Any], discovery: dict[str, Any], model_name: str) -> str | None:
    for provider in providers:
        entry = discovery.get(provider.name) if isinstance(discovery.get(provider.name), dict) else {}
        models = entry.get("models") if isinstance(entry.get("models"), list) else []
        if model_name in [str(item) for item in models]:
            return provider.name
        if provider.model == model_name:
            return provider.name
    return providers[0].name if providers else None


def _maybe_pull_model_artifact(
    *,
    workspace_root: Path,
    client: OciClient,
    provider_name: str | None,
    model_name: str,
) -> dict[str, Any] | None:
    if not provider_name:
        return None
    service = EmbeddingsConfigService(workspace_root)
    provider = service.get_provider(provider_name)
    policy = provider.model_artifacts if isinstance(provider.model_artifacts, dict) else None
    if not policy:
        return None
    if str(policy.get("source") or "").strip().lower() != "oci":
        return None
    template = str(policy.get("ref_template") or "").strip()
    if not template:
        return None
    ref = template.format(model=model_name, provider=provider_name)
    digest = client.resolve(ref)
    cache_dir = workspace_root / "cache" / "models" / provider_name / model_name.replace("/", "_")
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    client.pull(ref, cache_dir)
    return {"ref": ref, "digest": digest, "path": str(cache_dir)}


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    data = str(value).strip()
    return data if data else None
