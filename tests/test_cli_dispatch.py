"""Behavioral tests for the CPM CLI dispatcher."""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from cpm_cli import main as cli_main

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "plugins"


def _ensure_workspace_plugins(root: Path) -> Path:
    plugins_dir = root / ".cpm" / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    return plugins_dir


def _copy_fixture_plugin(name: str, destination: Path) -> None:
    shutil.copytree(FIXTURE_ROOT / name, destination, dirs_exist_ok=True)


def _create_conflict_plugin(path: Path, *, group: str, command_name: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    manifest = textwrap.dedent(
        f"""
        [plugin]
        id = "{path.name}"
        name = "Conflict Plugin"
        version = "0.1.0"
        group = "{group}"
        entrypoint = "{path.name}.entrypoint:PluginEntrypoint"
        requires_cpm = ">=0.1.0"
        """
    ).strip()
    (path / "plugin.toml").write_text(manifest + "\n")

    features_code = textwrap.dedent(
        f"""
        \"\"\"Conflict command for testing \"{command_name}\".\"\"\"

        from argparse import ArgumentParser
        from typing import Sequence

        from cpm_core.api.abc import CPMAbstractCommand
        from cpm_core.api.decorators import cpmcommand


        @cpmcommand(name=\"{command_name}\")
        class ConflictCommand(CPMAbstractCommand):
            @classmethod
            def configure(cls, parser: ArgumentParser) -> None:
                parser.add_argument(\"--flag\", action=\"store_true\")

            def run(self, argv: Sequence[str]) -> int:
                self.argv = argv
                return 0
        """
    )
    package_dir = path / path.name
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").write_text("")
    (package_dir / "features.py").write_text(features_code)

    entrypoint_code = textwrap.dedent(
        """\
        \"\"\"Entrypoint for the conflict plugin.\"\"\"

        from . import features


        class PluginEntrypoint:
            def init(self, ctx) -> None:
                _ = features.ConflictCommand
        """
    )
    (package_dir / "entrypoint.py").write_text(entrypoint_code)


def test_global_help_posts_core_before_plugins(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plugins_dir = _ensure_workspace_plugins(tmp_path)
    _copy_fixture_plugin("sample_plugin", plugins_dir / "sample_plugin")

    code = cli_main(["--help"], start_dir=tmp_path)
    assert code == 0
    captured = capsys.readouterr()
    content = captured.out
    assert "Core commands" in content
    assert "Plugin commands" in content
    assert content.index("Core commands") < content.index("Plugin commands")
    assert "sample-command" in content


def test_plugin_list_hides_builtins_by_default(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plugins_dir = _ensure_workspace_plugins(tmp_path)
    _copy_fixture_plugin("sample_plugin", plugins_dir / "sample_plugin")

    code = cli_main(["plugin", "list"], start_dir=tmp_path)
    assert code == 0
    output = [line.strip() for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert "sample_plugin" in output
    assert "core" not in output

    code = cli_main(["plugin", "list", "--include-builtin"], start_dir=tmp_path)
    assert code == 0
    output = [line.strip() for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert "core" in output


def test_ambiguous_name_errors_with_group_hint(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plugins_dir = _ensure_workspace_plugins(tmp_path)
    _create_conflict_plugin(
        plugins_dir / "conflict_plugin", group="conflict", command_name="list"
    )

    code = cli_main(["list"], start_dir=tmp_path)
    assert code == 1
    assert "use group:name" in capsys.readouterr().out


def test_group_name_and_colon_resolution(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plugins_dir = _ensure_workspace_plugins(tmp_path)
    _copy_fixture_plugin("sample_plugin", plugins_dir / "sample_plugin")

    code = cli_main(["sample:sample-command"], start_dir=tmp_path)
    assert code == 0
    capsys.readouterr()

    code = cli_main(["sample", "sample-command"], start_dir=tmp_path)
    assert code == 0
    capsys.readouterr()
