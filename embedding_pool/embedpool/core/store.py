from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

from .types import ConfigFile, PoolFile, ModelSpec, DriverSpec, ScalingSpec, QueueSpec


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_config(path: str) -> ConfigFile:
    d = _read_yaml(Path(path))
    cfg = ConfigFile()
    cfg.version = int(d.get("version") or 1)

    client = d.get("client") or {}
    server = d.get("server") or {}
    paths = d.get("paths") or {}
    proc = d.get("process") or {}
    logging = d.get("logging") or {}
    defaults = d.get("defaults") or {}
    hot = d.get("hot_reload") or {}

    cfg.client_base_url = str(client.get("base_url") or cfg.client_base_url)

    cfg.server_host = str(server.get("host") or cfg.server_host)
    cfg.server_port = int(server.get("port") or cfg.server_port)

    cfg.root = str(paths.get("root") or cfg.root)
    cfg.pool_yml = str(paths.get("pool_yml") or cfg.pool_yml)
    cfg.config_yml = str(paths.get("config_yml") or cfg.config_yml)
    cfg.state_dir = str(paths.get("state_dir") or cfg.state_dir)
    cfg.logs_dir = str(paths.get("logs_dir") or cfg.logs_dir)
    cfg.cache_dir = str(paths.get("cache_dir") or cfg.cache_dir)

    cfg.pid_file = str(proc.get("pid_file") or cfg.pid_file)

    cfg.log_level = str(logging.get("level") or cfg.log_level)

    cfg.request_timeout_s = int(defaults.get("request_timeout_s") or cfg.request_timeout_s)
    cfg.max_queue_per_model = int(defaults.get("max_queue_per_model") or cfg.max_queue_per_model)
    cfg.max_inflight_global = int(defaults.get("max_inflight_global") or cfg.max_inflight_global)

    cfg.hot_reload_enabled = bool(hot.get("enabled")) if "enabled" in hot else cfg.hot_reload_enabled
    return cfg


def save_config(path: str, cfg: ConfigFile) -> None:
    data: Dict[str, Any] = {
        "version": cfg.version,
        "client": {"base_url": cfg.client_base_url},
        "server": {"host": cfg.server_host, "port": cfg.server_port},
        "paths": {
            "root": cfg.root,
            "pool_yml": cfg.pool_yml,
            "config_yml": cfg.config_yml,
            "state_dir": cfg.state_dir,
            "logs_dir": cfg.logs_dir,
            "cache_dir": cfg.cache_dir,
        },
        "process": {"pid_file": cfg.pid_file},
        "logging": {"level": cfg.log_level},
        "defaults": {
            "request_timeout_s": cfg.request_timeout_s,
            "max_queue_per_model": cfg.max_queue_per_model,
            "max_inflight_global": cfg.max_inflight_global,
        },
        "hot_reload": {"enabled": cfg.hot_reload_enabled},
    }
    _write_yaml(Path(path), data)


def load_pool(path: str) -> PoolFile:
    d = _read_yaml(Path(path))
    pf = PoolFile(version=int(d.get("version") or 1), models=[])

    raw = d.get("models") or []
    if not isinstance(raw, list):
        return pf

    for m in raw:
        if not isinstance(m, dict):
            continue
        name = str(m.get("model") or "").strip()
        if not name:
            continue
        alias = m.get("alias")
        alias = str(alias).strip() if alias else None

        driver = m.get("driver") or {}
        driver_type = str(driver.get("type") or "local_st").strip()
        driver_cfg = driver.get("config") or {}
        if not isinstance(driver_cfg, dict):
            driver_cfg = {}

        scaling = m.get("scaling") or {}
        queue = m.get("queue") or {}

        pf.models.append(
            ModelSpec(
                model=name,
                alias=alias,
                enabled=bool(m.get("enabled")) if "enabled" in m else True,
                driver=DriverSpec(type=driver_type, config=dict(driver_cfg)),
                scaling=ScalingSpec(
                    min=int(scaling.get("min") or 1),
                    max=int(scaling.get("max") or 1),
                    idle_ttl_s=int(scaling.get("idle_ttl_s") or 30),
                ),
                queue=QueueSpec(
                    max_size=int(queue.get("max_size") or 1000),
                    max_inflight_per_replica=int(queue.get("max_inflight_per_replica") or 1),
                ),
            )
        )
    return pf


def save_pool(path: str, pf: PoolFile) -> None:
    out: List[Dict[str, Any]] = []
    for m in pf.models:
        out.append({
            "model": m.model,
            **({"alias": m.alias} if m.alias else {}),
            "enabled": bool(m.enabled),
            "driver": {"type": m.driver.type, "config": dict(m.driver.config or {})},
            "scaling": {"min": m.scaling.min, "max": m.scaling.max, "idle_ttl_s": m.scaling.idle_ttl_s},
            "queue": {"max_size": m.queue.max_size, "max_inflight_per_replica": m.queue.max_inflight_per_replica},
        })
    _write_yaml(Path(path), {"version": pf.version, "models": out})
