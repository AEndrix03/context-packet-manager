"""console script entrypoint for the CPM CLI."""

from .main import main


def run() -> int:
    return main()


if __name__ == "__main__":
    raise SystemExit(run())
