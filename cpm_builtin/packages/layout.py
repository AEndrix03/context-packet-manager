"""Layout helpers for the ~/.cpm/packages and state directories."""

from __future__ import annotations

from pathlib import Path

from .versions import split_version_parts

__all__ = [
    "active_root",
    "pins_root",
    "packages_root",
    "state_root",
    "version_dir",
]

PACKAGES_DIR_NAME = "packages"
STATE_DIR_NAME = "state"
PINS_DIR_NAME = "pins"
ACTIVE_DIR_NAME = "active"


def packages_root(root: Path) -> Path:
    return root / PACKAGES_DIR_NAME


def state_root(root: Path) -> Path:
    return root / STATE_DIR_NAME


def pins_root(root: Path) -> Path:
    return state_root(root) / PINS_DIR_NAME


def active_root(root: Path) -> Path:
    return state_root(root) / ACTIVE_DIR_NAME


def version_dir(root: Path, name: str, version: str) -> Path:
    parts = split_version_parts(version)
    return packages_root(root) / name / Path(*parts)
