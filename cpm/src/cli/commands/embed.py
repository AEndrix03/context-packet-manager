import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

import requests
import uvicorn

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8876


def _server_url(host: str, port: int) -> str:
    return f"http://{host}:{int(port)}"


def _pidfile_path(cpm_dir: str) -> Path:
    # pid file dentro .cpm (o custom)
    return Path(cpm_dir) / "embed-server.pid"


def _probe_health(url: str, timeout_s: float = 0.8) -> bool:
    try:
        r = requests.get(f"{url}/health", timeout=timeout_s)
        return r.ok
    except Exception:
        return False


def _read_pid(pidfile: Path) -> Optional[int]:
    try:
        s = pidfile.read_text(encoding="utf-8").strip()
        return int(s)
    except Exception:
        return None


def _write_pid(pidfile: Path, pid: int) -> None:
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(int(pid)), encoding="utf-8")


def _kill_pid(pid: int) -> bool:
    """
    Best-effort cross-platform terminate.
    Returns True if kill signal was sent successfully.
    """
    try:
        if os.name == "nt":
            # taskkill è più affidabile su Windows
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return True
        else:
            os.kill(pid, signal.SIGTERM)
            return True
    except Exception:
        return False


def cmd_cpm_embed_start_server(args) -> None:
    host = args.host
    port = int(args.port)
    cpm_dir = args.cpm_dir
    url = _server_url(host, port)
    pidfile = _pidfile_path(cpm_dir)

    if _probe_health(url):
        print(f"[cpm:embed] server already running at {url}")
        return

    print("[cpm:embed] starting embedding server")
    print(f"[cpm:embed] host={host} port={port}")

    if args.detach:
        # Avvio detached: nuovo processo python -m uvicorn ...
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "rag.embedding.embedding_server:app",
            "--host",
            host,
            "--port",
            str(port),
            "--log-level",
            args.log_level,
        ]

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

        with open(os.devnull, "wb") as devnull:
            p = subprocess.Popen(
                cmd,
                stdout=devnull,
                stderr=devnull,
                stdin=devnull,
                creationflags=creationflags,
                close_fds=True,
            )

        _write_pid(pidfile, p.pid)
        print(f"[cpm:embed] started (detached) pid={p.pid}")
        print(f"[cpm:embed] url={url}")
        print(f"[cpm:embed] pidfile={pidfile.as_posix()}")
        print("[cpm:embed] tip: rag cpm embed stop-server")
        return

    print("[cpm:embed] press CTRL+C to stop")
    uvicorn.run(
        "rag.embedding.embedding_server:app",
        host=host,
        port=port,
        log_level=args.log_level,
    )


def cmd_cpm_embed_attach_server(args) -> None:
    """
    NON può “attaccarsi” a un processo detached in modo portabile (specialmente su Windows).
    Questo comando serve come UX: avvia il server in foreground (con log) usando stessi host/port.
    """
    host = args.host
    port = int(args.port)
    url = _server_url(host, port)

    if _probe_health(url):
        print(f"[cpm:embed] server already running at {url}")
        print(
            "[cpm:embed] note: cannot attach to an existing detached process; use stop-server then start-server (foreground) if you need logs.")
        return

    print("[cpm:embed] starting embedding server (foreground)")
    print(f"[cpm:embed] host={host} port={port}")
    print("[cpm:embed] press CTRL+C to stop")
    uvicorn.run(
        "rag.embedding.embedding_server:app",
        host=host,
        port=port,
        log_level=args.log_level,
    )


def cmd_cpm_embed_stop_server(args) -> None:
    cpm_dir = args.cpm_dir
    pidfile = _pidfile_path(cpm_dir)
    pid = _read_pid(pidfile)

    if pid is None:
        print(f"[cpm:embed] no pidfile found: {pidfile.as_posix()}")
        print("[cpm:embed] start with: rag cpm embed start-server --detach")
        return

    ok = _kill_pid(pid)
    if ok:
        try:
            pidfile.unlink(missing_ok=True)  # py>=3.8
        except Exception:
            pass
        print(f"[cpm:embed] stop-server sent to pid={pid}")
    else:
        print(f"[cpm:embed] failed to stop pid={pid}")
        print("[cpm:embed] you may need to stop it manually")


def cmd_cpm_embed_status(args) -> None:
    host = args.host
    port = int(args.port)
    url = _server_url(host, port)

    try:
        r = requests.get(f"{url}/health", timeout=1.5)
    except Exception:
        r = None

    if not r or not r.ok:
        print(f"[cpm:embed] DOWN {url}")
        return

    data = r.json()
    loaded = data.get("loaded", [])
    print(f"[cpm:embed] UP {url} loaded_models={len(loaded)}")
    if loaded:
        for m in loaded:
            print(f"  - {m}")


def add_cpm_embed_commands(subparsers: argparse._SubParsersAction) -> None:
    embed = subparsers.add_parser("embed", help="Embedding server management")
    embed_sub = embed.add_subparsers(dest="embed_cmd", required=True)

    # start-server
    start = embed_sub.add_parser("start-server", help="Start the embedding HTTP server")
    start.add_argument("--host", default=DEFAULT_HOST, help=f"Bind host (default: {DEFAULT_HOST})")
    start.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Bind port (default: {DEFAULT_PORT})")
    start.add_argument("--detach", action="store_true", help="Start server detached and return immediately")
    start.add_argument("--log-level", default="warning",
                       choices=["critical", "error", "warning", "info", "debug", "trace"],
                       help="Uvicorn log level (default: warning)")
    start.add_argument("--cpm_dir", default=".cpm", help="Where to store pidfile (default: .cpm)")
    start.set_defaults(func=cmd_cpm_embed_start_server)

    # attach-server (foreground start with logs)
    attach = embed_sub.add_parser("attach-server", help="Start server in foreground (cannot attach to detached)")
    attach.add_argument("--host", default=DEFAULT_HOST, help=f"Bind host (default: {DEFAULT_HOST})")
    attach.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Bind port (default: {DEFAULT_PORT})")
    attach.add_argument("--log-level", default="info",
                        choices=["critical", "error", "warning", "info", "debug", "trace"],
                        help="Uvicorn log level (default: info)")
    attach.set_defaults(func=cmd_cpm_embed_attach_server)

    # stop-server (uses pidfile)
    stop = embed_sub.add_parser("stop-server", help="Stop a detached embedding server (pidfile-based)")
    stop.add_argument("--cpm_dir", default=".cpm", help="Folder containing pidfile (default: .cpm)")
    stop.set_defaults(func=cmd_cpm_embed_stop_server)

    # status
    status = embed_sub.add_parser("status", help="Check embedding server health")
    status.add_argument("--host", default=DEFAULT_HOST, help=f"Server host (default: {DEFAULT_HOST})")
    status.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Server port (default: {DEFAULT_PORT})")
    status.set_defaults(func=cmd_cpm_embed_status)
