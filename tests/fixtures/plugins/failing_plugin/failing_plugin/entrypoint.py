"""Entrypoint for the failing plugin fixture."""


class FailingPlugin:
    def init(self, ctx) -> None:
        raise RuntimeError("unable to initialize")
