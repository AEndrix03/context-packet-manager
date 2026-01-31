from __future__ import annotations

import argparse
import os

import uvicorn

from .app import create_app


def main():
    ap = argparse.ArgumentParser(prog="embedpool-server")
    ap.add_argument("--config", default=".config/config.yml")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--log-level", default="info")
    args = ap.parse_args()

    cfg_path = args.config
    app = create_app(cfg_path)

    # Allow overriding host/port, otherwise config.yml values are used by the user anyway.
    host = args.host or os.environ.get("EMBEDPOOL_HOST") or "127.0.0.1"
    port = args.port or int(os.environ.get("EMBEDPOOL_PORT") or 8876)

    uvicorn.run(app, host=host, port=port, log_level=args.log_level)


if __name__ == "__main__":
    main()
