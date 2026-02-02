from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Literal

DriverType = Literal["local_st", "http", "subprocess"]


@dataclass
class DriverSpec:
    type: DriverType
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScalingSpec:
    min: int = 1
    max: int = 1
    idle_ttl_s: int = 30


@dataclass
class QueueSpec:
    max_size: int = 1000
    max_inflight_per_replica: int = 1


@dataclass
class ModelSpec:
    model: str
    alias: Optional[str] = None
    enabled: bool = True
    driver: DriverSpec = field(default_factory=lambda: DriverSpec(type="local_st", config={}))
    scaling: ScalingSpec = field(default_factory=ScalingSpec)
    queue: QueueSpec = field(default_factory=QueueSpec)


@dataclass
class PoolFile:
    version: int = 1
    models: List[ModelSpec] = field(default_factory=list)


@dataclass
class ConfigFile:
    version: int = 1

    client_base_url: str = "http://127.0.0.1:8876"

    server_host: str = "127.0.0.1"
    server_port: int = 8876

    root: str = ".config"
    pool_yml: str = ".config/pool.yml"
    config_yml: str = ".config/config.yml"
    state_dir: str = ".config/state"
    logs_dir: str = ".config/logs"
    cache_dir: str = ".config/cache"
    pid_file: str = ".config/state/pool.pid"

    log_level: str = "info"

    request_timeout_s: int = 120
    max_queue_per_model: int = 1000
    max_inflight_global: int = 256

    hot_reload_enabled: bool = True
