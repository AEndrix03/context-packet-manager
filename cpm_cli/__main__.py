"""console script entrypoint for the CPM CLI."""

from .main import main


def run() -> int:
    return main()


def main() -> int:
    """Console entrypoint used by setuptools script hooks."""
    return run()


if __name__ == "__main__":
    raise SystemExit(run())
