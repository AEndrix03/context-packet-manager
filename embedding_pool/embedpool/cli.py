from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import requests

from .core.store import load_config, load_pool, save_pool
from .core.types import ModelSpec, DriverSpec, ScalingSpec, QueueSpec
from .core.util import ensure_dirs, env_override_pool_url


def _cfg_path(args) -> str:
    return args.config or ".config/config.yml"


def _pool_url(cfg_path: str) -> str:
    cfg = load_config(cfg_path)
    return env_override_pool_url(cfg.client_base_url)


def _pidfile(cfg_path: str) -> Path:
    cfg = load_config(cfg_path)
    return Path(cfg.pid_file)


def _probe(url: str) -> bool:
    try:
        r = requests.get(f"{url.rstrip('/')}/health", timeout=0.6)
        return r.ok
    except Exception:
        return False


def cmd_init(args) -> None:
    root = Path(args.root or ".config").resolve()
    ensure_dirs(str(root), str(root / "state"), str(root / "logs"), str(root / "cache"))

    config_yml = root / "config.yml"
    pool_yml = root / "pool.yml"

    if not config_yml.exists():
        config_yml.write_text(
            """version: 1
client:
  base_url: "http://127.0.0.1:8876"
server:
  host: "127.0.0.1"
  port: 8876
paths:
  root: ".config"
  pool_yml: ".config/pool.yml"
  config_yml: ".config/config.yml"
  state_dir: ".config/state"
  logs_dir: ".config/logs"
  cache_dir: ".config/cache"
process:
  pid_file: ".config/state/pool.pid"
logging:
  level: "info"
defaults:
  request_timeout_s: 120
  max_queue_per_model: 1000
  max_inflight_global: 256
hot_reload:
  enabled: true
""",
            encoding="utf-8",
        )

    if not pool_yml.exists():
        pool_yml.write_text("version: 1\nmodels: []\n", encoding="utf-8")

    print(f"[embedpool] initialized at {root.as_posix()}")


def cmd_register(args) -> None:
    cfg_path = _cfg_path(args)
    url = _pool_url(cfg_path)

    payload: Dict[str, Any] = {
        "model": args.model,
        "alias": args.alias or None,
        "enabled": True,
        "driver_type": args.type,
        "driver_config": {},
        "min": int(args.min),
        "max": int(args.max),
        "idle_ttl_s": int(args.idle_ttl_s),
        "queue_max_size": int(args.queue_max),
        "max_inflight_per_replica": int(args.inflight),
    }

    if args.type == "http":
        if not args.base_url:
            raise SystemExit("[embedpool] register http requires --base-url")
        payload["driver_config"] = {
            "base_url": args.base_url,
            "remote_model": (args.remote_model or args.model),
            "timeout_s": float(args.timeout_s),
        }
    elif args.type == "local_st":
        payload["driver_config"] = {
            "max_seq_length": int(args.max_seq_length),
            "normalize": bool(args.normalize),
            "dtype": args.dtype,
        }
    else:
        raise SystemExit(f"[embedpool] unsupported type {args.type!r}")

    if _probe(url):
        r = requests.post(f"{url.rstrip('/')}/models/register", json=payload, timeout=5.0)
        if not r.ok:
            raise SystemExit(f"[embedpool] register failed: {r.status_code} {r.text}")
        print(f"[embedpool] registered {args.model}")
        return

    # offline edit of pool.yml
    cfg = load_config(cfg_path)
    pf = load_pool(cfg.pool_yml)
    found = False
    for m in pf.models:
        if m.model == args.model:
            found = True
            m.alias = args.alias or None
            m.enabled = True
            m.driver.type = args.type
            m.driver.config = payload["driver_config"]
            m.scaling.min = int(args.min)
            m.scaling.max = int(args.max)
            m.scaling.idle_ttl_s = int(args.idle_ttl_s)
            m.queue.max_size = int(args.queue_max)
            m.queue.max_inflight_per_replica = int(args.inflight)
            break

    if not found:
        pf.models.append(
            ModelSpec(
                model=args.model,
                alias=args.alias or None,
                enabled=True,
                driver=DriverSpec(type=args.type, config=payload["driver_config"]),
                scaling=ScalingSpec(min=int(args.min), max=int(args.max), idle_ttl_s=int(args.idle_ttl_s)),
                queue=QueueSpec(max_size=int(args.queue_max), max_inflight_per_replica=int(args.inflight)),
            )
        )

    save_pool(cfg.pool_yml, pf)
    print(f"[embedpool] registered (offline) {args.model}")


def cmd_alias(args) -> None:
    cfg_path = _cfg_path(args)
    url = _pool_url(cfg_path)
    alias = args.alias
    if alias is not None and alias.strip().lower() in ("null", "none", ""):
        alias = None

    if _probe(url):
        r = requests.post(f"{url.rstrip('/')}/models/alias", json={"model": args.model, "alias": alias}, timeout=5.0)
        if not r.ok:
            raise SystemExit(f"[embedpool] alias failed: {r.status_code} {r.text}")
        print("[embedpool] ok")
        return

    cfg = load_config(cfg_path)
    pf = load_pool(cfg.pool_yml)
    ok = False
    for m in pf.models:
        if m.model == args.model or (m.alias and m.alias == args.model):
            m.alias = alias
            ok = True
    if not ok:
        raise SystemExit(f"[embedpool] unknown model/alias: {args.model}")
    save_pool(cfg.pool_yml, pf)
    print("[embedpool] ok")


def cmd_enable(args, enabled: bool) -> None:
    cfg_path = _cfg_path(args)
    url = _pool_url(cfg_path)

    if _probe(url):
        r = requests.post(f"{url.rstrip('/')}/models/enable", json={"model": args.model, "enabled": enabled},
                          timeout=5.0)
        if not r.ok:
            raise SystemExit(f"[embedpool] enable/disable failed: {r.status_code} {r.text}")
        print("[embedpool] ok")
        return

    cfg = load_config(cfg_path)
    pf = load_pool(cfg.pool_yml)
    ok = False
    for m in pf.models:
        if m.model == args.model or (m.alias and m.alias == args.model):
            m.enabled = enabled
            ok = True
    if not ok:
        raise SystemExit(f"[embedpool] unknown model/alias: {args.model}")
    save_pool(cfg.pool_yml, pf)
    print("[embedpool] ok")


def cmd_unregister(args) -> None:
    cfg_path = _cfg_path(args)
    url = _pool_url(cfg_path)

    if _probe(url):
        r = requests.delete(f"{url.rstrip('/')}/models/{args.model}", timeout=5.0)
        if not r.ok:
            raise SystemExit(f"[embedpool] unregister failed: {r.status_code} {r.text}")
        print("[embedpool] ok")
        return

    cfg = load_config(cfg_path)
    pf = load_pool(cfg.pool_yml)
    before = len(pf.models)
    pf.models = [m for m in pf.models if m.model != args.model and (m.alias != args.model)]
    if len(pf.models) == before:
        raise SystemExit(f"[embedpool] unknown model/alias: {args.model}")
    save_pool(cfg.pool_yml, pf)
    print("[embedpool] ok")


def cmd_pool_start(args) -> None:
    cfg_path = _cfg_path(args)
    cfg = load_config(cfg_path)
    url = _pool_url(cfg_path)
    pidfile = Path(cfg.pid_file)

    if _probe(url):
        print(f"[embedpool] already running at {url}")
        return

    if args.detach:
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        env = dict(os.environ)
        env["EMBEDPOOL_CONFIG"] = cfg_path

        p = subprocess.Popen(
            [sys.executable, "-m", "embedpool.server", "--config", cfg_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
            env=env,
        )
        pidfile.parent.mkdir(parents=True, exist_ok=True)
        pidfile.write_text(str(p.pid), encoding="utf-8")
        print(f"[embedpool] started pid={p.pid}")
        return

    subprocess.run([sys.executable, "-m", "embedpool.server", "--config", cfg_path], check=False)


def cmd_pool_stop(args) -> None:
    cfg_path = _cfg_path(args)
    pidfile = _pidfile(cfg_path)
    if not pidfile.exists():
        print("[embedpool] no pidfile")
        return
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
    except Exception:
        print("[embedpool] invalid pidfile")
        return

    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)
    else:
        try:
            os.kill(pid, 15)
        except Exception:
            pass
    try:
        pidfile.unlink(missing_ok=True)
    except Exception:
        pass
    print("[embedpool] stop sent")


def cmd_pool_status(args) -> None:
    cfg_path = _cfg_path(args)
    url = _pool_url(cfg_path)
    try:
        r = requests.get(f"{url.rstrip('/')}/status", timeout=1.5)
        if not r.ok:
            print(f"[embedpool] DOWN {url}")
            return
        data = r.json()
        print(f"[embedpool] UP {url}")
        for m in data.get("models") or []:
            print(
                f"  - model={m.get('model')} enabled={m.get('enabled')} "
                f"replicas={m.get('replicas')} idle={m.get('replicas_idle')} busy={m.get('replicas_busy')} "
                f"queue={m.get('queue_len')} driver={m.get('driver_type')}"
            )
    except Exception:
        print(f"[embedpool] DOWN {url}")


def cmd_pool_health(args) -> None:
    cfg_path = _cfg_path(args)
    url = _pool_url(cfg_path)
    print(f"[embedpool] {'OK' if _probe(url) else 'DOWN'} {url}")


def main():
    ap = argparse.ArgumentParser(prog="embedpool")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("--root", default=".config")
    p_init.set_defaults(func=cmd_init)

    p_reg = sub.add_parser("register")
    p_reg.add_argument("--config", default=".config/config.yml")
    p_reg.add_argument("--model", required=True)
    p_reg.add_argument("--alias", default=None)
    p_reg.add_argument("--type", choices=["local_st", "http"], required=True)
    p_reg.add_argument("--min", type=int, default=1)
    p_reg.add_argument("--max", type=int, default=1)
    p_reg.add_argument("--idle-ttl-s", type=int, default=30)
    p_reg.add_argument("--queue-max", type=int, default=1000)
    p_reg.add_argument("--inflight", type=int, default=1)
    p_reg.add_argument("--max-seq-length", type=int, default=1024)
    p_reg.add_argument("--normalize", action="store_true", default=True)
    p_reg.add_argument("--dtype", choices=["float32", "float16"], default="float32")
    p_reg.add_argument("--base-url", default="")
    p_reg.add_argument("--remote-model", default="")
    p_reg.add_argument("--timeout-s", type=float, default=120.0)
    p_reg.set_defaults(func=cmd_register)

    p_alias = sub.add_parser("set-alias")
    p_alias.add_argument("--config", default=".config/config.yml")
    p_alias.add_argument("--model", required=True)
    p_alias.add_argument("--alias", default=None)
    p_alias.set_defaults(func=cmd_alias)

    p_en = sub.add_parser("enable")
    p_en.add_argument("--config", default=".config/config.yml")
    p_en.add_argument("--model", required=True)
    p_en.set_defaults(func=lambda a: cmd_enable(a, True))

    p_dis = sub.add_parser("disable")
    p_dis.add_argument("--config", default=".config/config.yml")
    p_dis.add_argument("--model", required=True)
    p_dis.set_defaults(func=lambda a: cmd_enable(a, False))

    p_un = sub.add_parser("unregister")
    p_un.add_argument("--config", default=".config/config.yml")
    p_un.add_argument("--model", required=True)
    p_un.set_defaults(func=cmd_unregister)

    p_pool = sub.add_parser("pool")
    pool_sub = p_pool.add_subparsers(dest="pool_cmd", required=True)

    p_start = pool_sub.add_parser("start")
    p_start.add_argument("--config", default=".config/config.yml")
    p_start.add_argument("--detach", action="store_true")
    p_start.set_defaults(func=cmd_pool_start)

    p_stop = pool_sub.add_parser("stop")
    p_stop.add_argument("--config", default=".config/config.yml")
    p_stop.set_defaults(func=cmd_pool_stop)

    p_stat = pool_sub.add_parser("status")
    p_stat.add_argument("--config", default=".config/config.yml")
    p_stat.set_defaults(func=cmd_pool_status)

    p_h = pool_sub.add_parser("health")
    p_h.add_argument("--config", default=".config/config.yml")
    p_h.set_defaults(func=cmd_pool_health)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
