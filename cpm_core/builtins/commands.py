"""Built-in features that are registered before any plugins load."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
from typing import Sequence

from cpm_builtin.embeddings import EmbeddingsConfigService
from cpm_core.api import CPMAbstractCommand, cpmcommand
from cpm_core.compat import (
    LEGACY_COMMAND_ALIASES,
    LegacyLayoutIssue,
    detect_legacy_layout,
)
from cpm_core.workspace import WorkspaceLayout, WorkspaceResolver


class _WorkspaceAwareCommand(CPMAbstractCommand):
    """Commands that need to resolve or create the workspace root."""

    def __init__(self) -> None:
        self.resolver = WorkspaceResolver()
        self.workspace_root: Path | None = None

    def _resolve(self, start_dir: str | Path | None) -> Path:
        return self.resolver.ensure_workspace(Path(start_dir) if start_dir else None)


@cpmcommand(name="init", group="cpm")
class InitCommand(_WorkspaceAwareCommand):
    """Ensure the workspace directory tree exists."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("--dir", "-d", dest="workspace_dir", default=".")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recreate the workspace layout even if it already exists.",
        )

    def run(self, argv: Sequence[str]) -> int:
        requested_dir = getattr(argv, "workspace_dir", None)
        self.workspace_root = self._resolve(requested_dir)
        return 0


@cpmcommand(name="list", group="plugin")
class PluginListCommand(CPMAbstractCommand):
    """Report which plugin sources would be configured."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--include-builtin",
            action="store_true",
            dest="include_builtin",
            help="Show built-in helpers alongside installed plugins.",
        )

    def run(self, argv: Sequence[str]) -> int:
        self.include_builtin = bool(getattr(argv, "include_builtin", False))
        return 0


@cpmcommand(name="doctor", group="plugin")
class PluginDoctorCommand(_WorkspaceAwareCommand):
    """Comprehensive health check for the workspace, plugins, and registry."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--workspace-dir",
            "-w",
            dest="workspace_dir",
            default=".",
            help="Workspace root directory (default: current folder)",
        )

    def run(self, argv: Sequence[str]) -> int:
        requested_dir = getattr(argv, "workspace_dir", None)
        workspace_root = self._resolve(requested_dir)
        self.workspace_root = workspace_root
        layout = WorkspaceLayout.from_root(
            workspace_root,
            self.resolver.config_filename,
            self.resolver.embeddings_filename,
        )

        service = EmbeddingsConfigService(layout.config_dir)
        legacy_issues = detect_legacy_layout(workspace_root, layout)

        from cpm_core.app import CPMApp

        app = CPMApp(start_dir=workspace_root)
        status = app.bootstrap()
        plugin_records = app.plugin_manager.plugin_records()
        registry = app.registry
        registry_status = registry.ping()

        self._print_summary(
            workspace_root=workspace_root,
            layout=layout,
            service=service,
            plugin_records=plugin_records,
            registry=registry,
            registry_status=registry_status,
            legacy_issues=legacy_issues,
        )
        return 0

    def _print_summary(
        self,
        *,
        workspace_root: Path,
        layout: WorkspaceLayout,
        service: EmbeddingsConfigService,
        plugin_records: Sequence["cpm_core.plugin.manager.PluginRecord"],
        registry: "cpm_core.registry.client.RegistryClient",
        registry_status: str,
        legacy_issues: list[LegacyLayoutIssue],
    ) -> None:
        self._print_workspace(workspace_root, layout)
        self._print_embedding(service, layout, workspace_root)
        self._print_plugins(plugin_records)
        self._print_registry(registry, registry_status)
        self._print_alias_hints()
        self._print_legacy_layout(legacy_issues)

    def _print_workspace(self, workspace_root: Path, layout: WorkspaceLayout) -> None:
        print(f"[cpm:doctor] workspace root: {workspace_root}")
        print(f"[cpm:doctor] config file: {layout.config_file} (exists={layout.config_file.exists()})")
        print(f"[cpm:doctor] layout dirs: packages={layout.packages_dir.name} state={layout.state_dir.name}")
        emb_exists = layout.embeddings_file.exists()
        print(f"[cpm:doctor] embeddings file: {layout.embeddings_file} (exists={emb_exists})")
        legacy_embed = workspace_root / "embeddings.yml"
        if legacy_embed.exists() and not emb_exists:
            print(
                f"[cpm:doctor] warning: legacy {legacy_embed} detected; "
                f"move under {layout.embeddings_file} and rerun `cpm doctor`"
            )

    def _print_embedding(
        self,
        service: EmbeddingsConfigService,
        layout: WorkspaceLayout,
        workspace_root: Path,
    ) -> None:
        default = service.default_provider()
        providers = service.list_providers()
        default_name = default.name if default else None
        print(
            f"[cpm:doctor] embedding providers: {len(providers)} "
            f"(default={default_name or 'none'})"
        )
        for provider in providers:
            extra = f" model={provider.model}" if provider.model else ""
            print(f"  - {provider.name}: {provider.url}{extra}")
        if not providers:
            print(
                "[cpm:doctor] no embedding providers configured; run "
                "`cpm embed add` (delegates to legacy CLI) to register one."
            )

    def _print_plugins(self, records: Sequence["cpm_core.plugin.manager.PluginRecord"]) -> None:
        print("[cpm:doctor] plugins:")
        if not records:
            print("  - no plugins detected")
            return
        for record in records:
            state = record.state.value
            info = f"{record.id} [{state}] (source={record.source})"
            if record.error:
                info += f" error={record.error}"
            print(f"  - {info}")

    def _print_registry(self, registry, status: str) -> None:
        print(
            f"[cpm:doctor] registry endpoint: {registry.endpoint} status={status} "
            f"(last ping={registry.status})"
        )

    def _print_alias_hints(self) -> None:
        print("[cpm:doctor] legacy command aliases:")
        for alias in LEGACY_COMMAND_ALIASES:
            note = f" ({alias.note})" if alias.note else ""
            print(f"  - {alias.legacy} -> {alias.replacement}{note}")

    def _print_legacy_layout(self, issues: list[LegacyLayoutIssue]) -> None:
        if not issues:
            print("[cpm:doctor] workspace layout is current (no legacy packet roots found).")
            return
        print("[cpm:doctor] legacy layout detected:")
        for issue in issues:
            details = []
            if issue.packet_name:
                details.append(f"name={issue.packet_name}")
            if issue.packet_version:
                details.append(f"version={issue.packet_version}")
            details_text = f" ({', '.join(details)})" if details else ""
            print(
                f"  - {issue.current_path} -> {issue.suggested_path}{details_text}"
            )
        print("[cpm:doctor] consider migrating these artifacts into the .cpm/packages hierarchy.")


@cpmcommand(name="help", group="cpm")
class HelpCommand(CPMAbstractCommand):
    """Display the list of available commands."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--long",
            action="store_true",
            dest="long_format",
            help="Show detailed help about each command.",
        )

    def run(self, argv: Sequence[str]) -> int:
        self.long_format = bool(getattr(argv, "long_format", False))
        return 0


@cpmcommand(name="listing", group="cpm")
class ListingCommand(HelpCommand):
    """Alias for ``cpm help`` that focuses on command listing."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help="Choose how the command list is rendered.",
        )

    def run(self, argv: Sequence[str]) -> int:
        self.output_format = getattr(argv, "format", "text")
        return super().run(argv)
