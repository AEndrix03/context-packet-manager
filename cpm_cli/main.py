"""New CPM CLI entrypoint backed by the CPM feature registry."""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path
from typing import Iterable, Sequence

from cpm_core.app import CPMApp
from cpm_core.registry import AmbiguousFeatureError, FeatureNotFoundError
from cpm_core.registry.entry import CPMRegistryEntry

CLI_VERSION = "0.1.0"


def main(
    argv: Sequence[str] | None = None,
    *,
    start_dir: Path | str | None = None,
) -> int:
    """Resolve and run a CPM command."""

    tokens = list(argv) if argv is not None else list(sys.argv[1:])
    if not tokens:
        return _print_overview(start_dir=start_dir)

    if tokens[0] in ("-h", "--help"):
        return _print_overview(start_dir=start_dir)

    if "--version" in tokens:
        print(f"cpm v{CLI_VERSION}")
        return 0

    app = CPMApp(start_dir=start_dir)
    app.bootstrap()
    registry = app.feature_registry
    entries = _ordered_entries(registry.entries())
    ambiguous = _ambiguous_names(entries)
    qualified_names = {entry.qualified_name for entry in entries}

    try:
        spec, command_args = _extract_command_spec(tokens, qualified_names)
        entry = registry.resolve(spec)
    except FeatureNotFoundError as exc:
        print(str(exc))
        return 1
    except AmbiguousFeatureError as exc:
        candidates = ", ".join(exc.candidates)
        print(
            f"Command is ambiguous ({candidates}); use group:name to disambiguate."
        )
        return 1

    parser = argparse.ArgumentParser(
        prog=f"cpm {_display_name(entry, ambiguous)}",
        description=_command_description(entry),
    )
    entry.target.configure(parser)

    try:
        parsed_args = parser.parse_args(command_args)
    except SystemExit as exc:
        return exc.code or 0

    command = entry.target()
    result = command.run(parsed_args)

    if entry.group == "cpm" and entry.name == "help":
        return _print_overview(
            start_dir=start_dir,
            entries=entries,
            ambiguous=ambiguous,
            include_long=getattr(command, "long_format", False),
        )

    if entry.group == "cpm" and entry.name == "listing":
        return _print_listing(entries, ambiguous, getattr(command, "output_format", "text"))

    if entry.group == "plugin" and entry.name == "list":
        return _print_plugin_list(
            app, include_builtin=getattr(command, "include_builtin", False)
        )

    return to_int(result)


def _print_overview(
    *,
    start_dir: Path | str | None = None,
    entries: Iterable[CPMRegistryEntry] | None = None,
    ambiguous: set[str] | None = None,
    include_long: bool = False,
) -> int:
    """Show the global help listing."""

    if entries is None:
        app = CPMApp(start_dir=start_dir)
        app.bootstrap()
        entries = _ordered_entries(app.feature_registry.entries())
    if ambiguous is None:
        ambiguous = _ambiguous_names(entries)

    print("Usage: cpm <command> [args...]\n")
    cores, plugins = _split_entries(entries)

    _render_section("Core commands", cores, ambiguous, include_long)
    if plugins:
        print()
        _render_section("Plugin commands", plugins, ambiguous, include_long)

    print("\nUse group:name to disambiguate commands when needed.")
    return 0


def _print_listing(entries: Iterable[CPMRegistryEntry], ambiguous: set[str], fmt: str) -> int:
    """Show the command listing."""

    names = [_display_name(entry, ambiguous) for entry in entries]
    if fmt == "json":
        print(json.dumps(names, indent=2))
        return 0

    for name in names:
        print(name)
    return 0


def _print_plugin_list(app: CPMApp, *, include_builtin: bool) -> int:
    """List the configured plugins."""

    plugins = list(app.plugin_manager.list_plugins())
    if not include_builtin:
        plugins = [name for name in plugins if name != "core"]
    if not plugins:
        print("No plugins configured.")
        return 0

    for name in plugins:
        print(name)
    return 0


def _render_section(
    title: str,
    entries: Iterable[CPMRegistryEntry],
    ambiguous: set[str],
    include_long: bool,
) -> None:
    print(title + ":")
    for entry in entries:
        display = _display_name(entry, ambiguous)
        description = _command_description(entry).strip()
        lines = description.splitlines()
        short = lines[0] if lines else ""
        print(f"  {display:<30} {short}")
        if include_long and len(lines) > 1:
            for extra in lines[1:]:
                print(f"    {extra}")


def _ordered_entries(entries: Iterable[CPMRegistryEntry]) -> list[CPMRegistryEntry]:
    entries = list(entries)
    cores, plugins = _split_entries(entries)
    return sorted(cores, key=lambda entry: entry.qualified_name) + sorted(
        plugins, key=lambda entry: entry.qualified_name
    )


def _split_entries(
    entries: Iterable[CPMRegistryEntry],
) -> tuple[list[CPMRegistryEntry], list[CPMRegistryEntry]]:
    cores: list[CPMRegistryEntry] = []
    plugins: list[CPMRegistryEntry] = []
    for entry in entries:
        if entry.origin == "builtin":
            cores.append(entry)
        else:
            plugins.append(entry)
    return cores, plugins


def _ambiguous_names(entries: Iterable[CPMRegistryEntry]) -> set[str]:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.name] = counts.get(entry.name, 0) + 1
    return {name for name, total in counts.items() if total > 1}


def _display_name(entry: CPMRegistryEntry, ambiguous: Iterable[str]) -> str:
    if entry.name in ambiguous:
        return entry.qualified_name
    return entry.name


def _command_description(entry: CPMRegistryEntry) -> str:
    doc = inspect.getdoc(entry.target) or ""
    return doc.strip()


def _extract_command_spec(args: Sequence[str], qualified_names: set[str]) -> tuple[str, list[str]]:
    first, *rest = args
    if ":" in first and first in qualified_names:
        return first, list(rest)

    if rest:
        maybe = f"{first}:{rest[0]}"
        if maybe in qualified_names:
            return maybe, list(rest[1:])

    return first, list(rest)


def to_int(result: int | None) -> int:
    return 0 if result is None else result
