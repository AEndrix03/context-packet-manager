"""Package inspection helpers for CPM builtins."""


def describe_package(name: str) -> str:
    """Return a textual summary of the placeholder package."""

    return f"package {name} is a built-in placeholder for CPM vNext."
