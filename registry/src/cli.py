from __future__ import annotations

import os
import sys
import signal
import subprocess
from pathlib import Path
from pathlib import Path

import typer
import uvicorn

from settings import RegistrySettings, load_env_file
from api import make_app  # run uvicorn with app object (avoid import-path issues)

app = typer.Typer(help="CPM Package Registry (server)")

PID_FILE = Path(".registry.pid")
LOG_FILE = Path(".registry.log")


# -------------------------
# Helpers
# -------------------------
def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# -------------------------
# SERVER
# -------------------------
@app.command("start")
def start(
    host: str = typer.Option(None, "--host"),
    port: int = typer.Option(None, "--port"),
    reload: bool = typer.Option(False, "--reload", help="Dev reload (disabled in this CLI mode)"),
    detach: bool = typer.Option(False, "--detach", help="Run registry in background"),
    env_file: str = typer.Option(None, "--env-file", help="Path to .env (default: registry/.env)"),
):
    """
    Start registry server.

    We start uvicorn with the FastAPI app object (not an import string),
    so it works regardless of repo layout / current working directory.

    NOTE: --reload is disabled here to avoid Windows silent failures & import path issues.
    """
    try:
        used_env = load_env_file(env_file)
        settings = RegistrySettings.from_env(env_file=env_file)

        host = host or settings.host
        port = port or settings.port

        if reload:
            typer.echo("Note: --reload disabled in this CLI mode (use `python -m uvicorn ... --reload` if needed).")
            reload = False

        if detach:
            if PID_FILE.exists():
                try:
                    pid = int(PID_FILE.read_text().strip())
                    if _is_process_alive(pid):
                        typer.echo(f"Registry already running (pid={pid})")
                        raise typer.Exit(1)
                except Exception:
                    pass
                PID_FILE.unlink(missing_ok=True)

            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            log = open(LOG_FILE, "ab", buffering=0)

            launcher = sys.argv[0] if sys.argv else "cpm-registry"
            launcher_path = Path(launcher)
            if launcher_path.suffix == ".py":
                cmd = [sys.executable, str(launcher_path), "start", "--host", host, "--port", str(port)]
            else:
                cmd = [launcher, "start", "--host", host, "--port", str(port)]
            if env_file:
                cmd.extend(["--env-file", env_file])

            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            PID_FILE.write_text(str(proc.pid))
            typer.echo(f"Registry started in background (pid={proc.pid})")
            typer.echo(f"Logs: {LOG_FILE}")
            typer.echo(f"Env file: {used_env}")
            return

        api_app = make_app(settings)

        typer.echo(f"Starting registry on http://{host}:{port}  (env: {used_env})")
        uvicorn.run(api_app, host=host, port=port, log_level="info")

    except Exception as e:
        typer.echo(f"ERROR starting registry: {type(e).__name__}: {e}")
        raise


@app.command("stop")
def stop():
    if not PID_FILE.exists():
        typer.echo("Registry not running (no pid file)")
        raise typer.Exit(1)

    pid_txt = PID_FILE.read_text().strip()
    try:
        pid = int(pid_txt)
    except ValueError:
        PID_FILE.unlink(missing_ok=True)
        typer.echo("Registry pid file corrupted; removed.")
        raise typer.Exit(1)

    if not _is_process_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        typer.echo("Registry was not running (stale pid file removed).")
        return

    try:
        if os.name == "nt":
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception as e:
        typer.echo(f"Failed to stop registry (pid={pid}): {e}")
        raise typer.Exit(1)

    PID_FILE.unlink(missing_ok=True)
    typer.echo(f"Registry stopped (pid={pid})")


@app.command("status")
def status():
    if not PID_FILE.exists():
        typer.echo("Registry: stopped")
        return

    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        typer.echo("Registry: stale pid file (corrupted) — removing")
        PID_FILE.unlink(missing_ok=True)
        return

    if _is_process_alive(pid):
        typer.echo(f"Registry: running (pid={pid})")
    else:
        typer.echo("Registry: stale pid file — removing")
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    app()
