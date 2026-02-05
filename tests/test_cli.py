"""Smoke tests for the CPM CLI surface."""

from pathlib import Path

import pytest

from cpm_builtin.packages import PackageManager
from cpm_builtin.packages.layout import version_dir
from cpm_cli import cli


def test_build_command_defaults() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["build"])
    assert args.command == "build"
    assert args.name == "default"


def test_cli_status_prints_workspace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_cpm = tmp_path / ".cpm"
    tmp_cpm.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    result = cli.main(["status"])
    assert result == 0
    captured = capsys.readouterr()
    assert "status: stub" in captured.out


def _write_version(workspace_root: Path, name: str, version: str) -> None:
    path = version_dir(workspace_root, name, version)
    path.mkdir(parents=True, exist_ok=True)
    (path / "cpm.yml").write_text(f"name: {name}\nversion: {version}\n")


def test_pkg_list_shows_packages(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PackageManager(tmp_path / ".cpm")
    _write_version(tmp_path / ".cpm", "sample", "0.1.0")
    _write_version(tmp_path / ".cpm", "sample", "0.2.0")
    manager.set_pinned_version("sample", "0.1.0")
    monkeypatch.chdir(tmp_path)

    code = cli.main(["pkg", "list"])
    assert code == 0
    captured = capsys.readouterr()
    assert "[cpm:pkg] sample" in captured.out
    assert "pinned=0.1.0" in captured.out


def test_pkg_use_updates_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = PackageManager(tmp_path / ".cpm")
    _write_version(tmp_path / ".cpm", "sample", "1.0.0")
    _write_version(tmp_path / ".cpm", "sample", "2.0.0")
    monkeypatch.chdir(tmp_path)

    code = cli.main(["pkg", "use", "sample@latest"])
    assert code == 0
    captured = capsys.readouterr()
    assert "pinned and activated" in captured.out
    assert manager.get_pinned_version("sample") == "2.0.0"
    assert manager.get_active_version("sample") == "2.0.0"
