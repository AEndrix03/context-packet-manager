"""Package management helpers exposed through the built-in CPM leaf commands."""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Sequence

from cpm_builtin.packages import PackageManager, parse_package_spec
from cpm_core.api import CPMAbstractCommand, cpmcommand
from .commands import _WorkspaceAwareCommand


@cpmcommand(name="pkg", group="cpm")
class PkgCommand(_WorkspaceAwareCommand):
    """Manage local context packets stored inside the workspace."""

    @classmethod
    def configure(cls, parser: ArgumentParser) -> None:
        parser.add_argument("--workspace-dir", default=".", help="Workspace root directory")
        sub = parser.add_subparsers(dest="pkg_cmd", required=True)

        use = sub.add_parser("use", help="Pin or activate a local packet version")
        use.add_argument("spec", help="name or name@<version|latest>")
        use.set_defaults(pkg_cmd="use")

        list_cmd = sub.add_parser("list", help="List installed packets")
        list_cmd.set_defaults(pkg_cmd="list")

        prune = sub.add_parser("prune", help="Prune old versions while keeping pinned/active")
        prune.add_argument("name", help="Package name")
        prune.add_argument("--keep", type=int, default=1, help="How many latest versions to keep")
        prune.set_defaults(pkg_cmd="prune")

        remove = sub.add_parser("remove", help="Remove a package and its state")
        remove.add_argument("name", help="Package name")
        remove.set_defaults(pkg_cmd="remove")

    def run(self, argv: Sequence[str]) -> int:
        workspace_root = self._resolve(getattr(argv, "workspace_dir", None))
        self.workspace_root = workspace_root
        manager = PackageManager(workspace_root)

        action = getattr(argv, "pkg_cmd", None)
        if action == "use":
            return self._run_use(manager, argv)
        if action == "list":
            return self._run_list(manager)
        if action == "prune":
            return self._run_prune(manager, argv)
        if action == "remove":
            return self._run_remove(manager, argv)

        print("[cpm:pkg] unsupported subcommand")
        return 1

    def _run_use(self, manager: PackageManager, argv: Sequence[str]) -> int:
        spec = getattr(argv, "spec", "")
        try:
            resolved = manager.use(spec)
        except ValueError as exc:
            print(f"[cpm:pkg] error: {exc}")
            return 1
        name, _ = parse_package_spec(spec)
        print(f"[cpm:pkg] {name}@{resolved} pinned and activated")
        return 0

    def _run_list(self, manager: PackageManager) -> int:
        packages = manager.list_packages()
        if not packages:
            print("[cpm:pkg] no packages installed")
            return 0
        for pkg in packages:
            versions = ", ".join(pkg.versions)
            pinned = pkg.pinned_version or "-"
            active = pkg.active_version or "-"
            print(f"[cpm:pkg] {pkg.name} versions=[{versions}] pinned={pinned} active={active}")
        return 0

    def _run_prune(self, manager: PackageManager, argv: Sequence[str]) -> int:
        try:
            removed = manager.prune(getattr(argv, "name", ""), keep=getattr(argv, "keep", 1))
        except ValueError as exc:
            print(f"[cpm:pkg] error: {exc}")
            return 1
        if not removed:
            print(f"[cpm:pkg] nothing pruned for {getattr(argv, 'name', '')}")
            return 0
        print(f"[cpm:pkg] removed versions for {getattr(argv, 'name', '')}: {', '.join(removed)}")
        return 0

    def _run_remove(self, manager: PackageManager, argv: Sequence[str]) -> int:
        manager.remove(getattr(argv, "name", ""))
        print(f"[cpm:pkg] package '{getattr(argv, 'name', '')}' removed")
        return 0
