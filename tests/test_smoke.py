"""Smoke tests that exercise CPMApp startup with and without plugins."""

import shutil
from pathlib import Path

from cpm_core import CPMApp


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "plugins"


def _copy_plugin(name: str, destination: Path) -> None:
    """Copy a plugin fixture into the workspace plugin directory."""

    shutil.copytree(FIXTURE_ROOT / name, destination)


def test_bootstrap_without_plugins(tmp_path: Path) -> None:
    app = CPMApp(start_dir=tmp_path)
    status = app.bootstrap()

    assert status.plugins == ("core",)
    assert status.commands == ("build", "default-builder", "doctor", "help", "init", "list", "listing")
    assert status.registry_status == "online"


def test_bootstrap_with_sample_plugin(tmp_path: Path) -> None:
    app = CPMApp(start_dir=tmp_path)
    plugins_dir = app.workspace.root / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    _copy_plugin("sample_plugin", plugins_dir / "sample_plugin")

    status = app.bootstrap()

    assert status.plugins == ("core", "sample_plugin")
    expected = (
        "build",
        "default-builder",
        "doctor",
        "help",
        "init",
        "list",
        "listing",
        "sample-builder",
        "sample-command",
    )
    assert status.commands == expected
    assert status.registry_status == "online"
