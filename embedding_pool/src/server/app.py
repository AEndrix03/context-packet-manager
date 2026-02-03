from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import numpy as np
from core.embed_cache import EmbedCache
from core.runtime import ModelRuntime
from core.store import load_config, load_pool, save_pool
from core.types import PoolFile, ModelSpec, DriverSpec, ScalingSpec, QueueSpec
from core.util import ensure_dirs
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

log = logging.getLogger("src")


class EmbedReq(BaseModel):
    model: str
    texts: list[str]
    options: dict[str, Any] = {}


class ReloadReq(BaseModel):
    reason: str = "manual"


class RegisterReq(BaseModel):
    model: str
    alias: Optional[str] = None
    enabled: bool = True
    driver_type: str = "local_st"
    driver_config: dict[str, Any] = {}
    min: int = 1
    max: int = 1
    idle_ttl_s: int = 30
    queue_max_size: int = 1000
    max_inflight_per_replica: int = 1


class EnableReq(BaseModel):
    model: str
    enabled: bool


class AliasReq(BaseModel):
    model: str
    alias: Optional[str] = None


def create_app(config_path: str) -> FastAPI:
    cfg = load_config(config_path)
    ensure_dirs(cfg.state_dir, cfg.logs_dir, cfg.cache_dir)

    logging.basicConfig(level=getattr(logging, cfg.log_level.upper(), logging.INFO))

    app = FastAPI(title="embedding-pool", version="0.1.0")
    state: Dict[str, Any] = {
        "cfg": cfg,
        "pool_path": cfg.pool_yml,
        "pool": None,
        "runtimes": {},
        "global_sem": asyncio.Semaphore(int(cfg.max_inflight_global)),
        "booted": False,
        "last_reload": None,
        "cache": EmbedCache(cfg.cache_dir),
    }

    def _alias_conflicts(pf: PoolFile) -> None:
        used: Dict[str, str] = {}
        for m in pf.models:
            if m.alias:
                if m.alias in used and used[m.alias] != m.model:
                    raise RuntimeError(f"alias conflict: {m.alias} used by {used[m.alias]} and {m.model}")
                used[m.alias] = m.model

    async def _apply_pool(pf: PoolFile) -> None:
        _alias_conflicts(pf)

        old: dict[str, ModelRuntime] = state["runtimes"]
        new_models = {m.model for m in pf.models}

        for model_name in list(old.keys()):
            if model_name not in new_models:
                await old[model_name].stop()
                old.pop(model_name, None)

        for ms in pf.models:
            rt: Optional[ModelRuntime] = old.get(ms.model)
            if rt is None:
                rt = ModelRuntime(ms, state["global_sem"])
                old[ms.model] = rt
                await rt.start()
            else:
                rt.spec = ms
                await rt.start()

        state["pool"] = pf
        state["booted"] = True

    async def reload_pool(reason: str) -> None:
        pf = load_pool(state["pool_path"])
        await _apply_pool(pf)

        # prune cache when pool changes: remove entries for deleted models
        try:
            cache: EmbedCache = state["cache"]
            allowed = [m.model for m in (pf.models or [])]
            removed_rows = cache.prune_models(allowed)
            if removed_rows:
                log.info("cache pruned: removed_rows=%s", removed_rows)
        except Exception:
            # non blocchiamo il reload per problemi cache
            pass

        state["last_reload"] = {"reason": reason}

    def resolve_model(name_or_alias: str) -> str:
        pf: PoolFile = state["pool"]
        if pf is None:
            raise RuntimeError("pool not loaded")
        x = (name_or_alias or "").strip()
        for m in pf.models:
            if m.model == x:
                return m.model
        for m in pf.models:
            if m.alias and m.alias == x:
                return m.model
        raise KeyError(x)

    @app.on_event("startup")
    async def _startup():
        await reload_pool("startup")

    @app.get("/health")
    async def health():
        pf: PoolFile = state["pool"]
        return {"ok": True, "booted": state["booted"], "models": len(pf.models) if pf else 0}

    @app.get("/status")
    async def status():
        pf: PoolFile = state["pool"]
        out = {"ok": True, "last_reload": state["last_reload"], "models": []}
        if not pf:
            return out
        for m in pf.models:
            rt = state["runtimes"].get(m.model)
            out["models"].append(rt.status() if rt else {"model": m.model, "enabled": m.enabled, "replicas": 0})
        return out

    @app.post("/reload")
    async def reload(req: ReloadReq):
        await reload_pool(req.reason)
        return {"ok": True}

    @app.post("/embed")
    async def embed(req: EmbedReq):
        if not req.texts:
            raise HTTPException(status_code=400, detail="texts must be non-empty")

        try:
            model_name = resolve_model(req.model)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown model/alias: {req.model}")

        rt: ModelRuntime = state["runtimes"].get(model_name)
        if rt is None:
            raise HTTPException(status_code=500, detail=f"runtime missing for model: {model_name}")

        cache: EmbedCache = state["cache"]

        # 1) cache lookup
        try:
            hashes, found = cache.get_many(model_name, list(req.texts))
        except Exception:
            hashes, found = ([], {})

        # 2) build missing batch
        missing_idx = [i for i in range(len(req.texts)) if i not in found]
        if not missing_idx:
            # all hit
            vecs = np.stack([found[i] for i in range(len(req.texts))], axis=0).astype(np.float32, copy=False)
            dim = int(vecs.shape[1])
            return {"model": model_name, "dim": dim, "vectors": vecs.tolist(), "meta": {"cache": "hit"}}

        missing_texts = [req.texts[i] for i in missing_idx]

        # 3) embed missing
        try:
            arr_missing, dim, meta = await rt.enqueue(missing_texts, dict(req.options or {}))
            if arr_missing.ndim == 1:
                arr_missing = arr_missing.reshape(1, -1)
            if arr_missing.dtype != np.float32:
                arr_missing = arr_missing.astype(np.float32)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        # 4) merge (original order)
        out = np.empty((len(req.texts), int(dim)), dtype=np.float32)
        for i, v in found.items():
            out[i] = v
        for j, i in enumerate(missing_idx):
            out[i] = arr_missing[j]

        # 5) save missing into cache
        try:
            miss_hashes = [hashes[i] for i in missing_idx] if hashes else []
            if miss_hashes and len(miss_hashes) == arr_missing.shape[0]:
                cache.put_many(model_name, miss_hashes, arr_missing)
        except Exception:
            pass

        # enrich meta
        meta = dict(meta or {})
        meta["cache"] = {"hits": len(found), "misses": len(missing_idx)}

        return {"model": model_name, "dim": int(dim), "vectors": out.tolist(), "meta": meta}

    # management endpoints (for live edits)
    @app.post("/models/register")
    async def models_register(req: RegisterReq):
        pf: PoolFile = state["pool"]
        if pf is None:
            raise HTTPException(status_code=500, detail="pool not loaded")

        existing: Optional[ModelSpec] = None
        for m in pf.models:
            if m.model == req.model:
                existing = m
                break

        if existing is None:
            pf.models.append(
                ModelSpec(
                    model=req.model,
                    alias=req.alias,
                    enabled=req.enabled,
                    driver=DriverSpec(type=req.driver_type, config=dict(req.driver_config or {})),
                    scaling=ScalingSpec(min=req.min, max=req.max, idle_ttl_s=req.idle_ttl_s),
                    queue=QueueSpec(max_size=req.queue_max_size, max_inflight_per_replica=req.max_inflight_per_replica),
                )
            )
        else:
            existing.alias = req.alias
            existing.enabled = bool(req.enabled)
            existing.driver.type = req.driver_type
            existing.driver.config = dict(req.driver_config or {})
            existing.scaling.min = int(req.min)
            existing.scaling.max = int(req.max)
            existing.scaling.idle_ttl_s = int(req.idle_ttl_s)
            existing.queue.max_size = int(req.queue_max_size)
            existing.queue.max_inflight_per_replica = int(req.max_inflight_per_replica)

        save_pool(state["pool_path"], pf)
        await reload_pool("register")
        return {"ok": True}

    @app.post("/models/enable")
    async def models_enable(req: EnableReq):
        pf: PoolFile = state["pool"]
        if pf is None:
            raise HTTPException(status_code=500, detail="pool not loaded")

        found_any = False
        for m in pf.models:
            if m.model == req.model or (m.alias and m.alias == req.model):
                m.enabled = bool(req.enabled)
                found_any = True
        if not found_any:
            raise HTTPException(status_code=404, detail=f"unknown model/alias: {req.model}")

        save_pool(state["pool_path"], pf)
        await reload_pool("enable")
        return {"ok": True}

    @app.post("/models/alias")
    async def models_alias(req: AliasReq):
        pf: PoolFile = state["pool"]
        if pf is None:
            raise HTTPException(status_code=500, detail="pool not loaded")

        found_any = False
        for m in pf.models:
            if m.model == req.model or (m.alias and m.alias == req.model):
                m.alias = (req.alias.strip() if req.alias else None)
                found_any = True
        if not found_any:
            raise HTTPException(status_code=404, detail=f"unknown model/alias: {req.model}")

        save_pool(state["pool_path"], pf)
        await reload_pool("alias")
        return {"ok": True}

    @app.delete("/models/{model_name}")
    async def models_delete(model_name: str):
        pf: PoolFile = state["pool"]
        if pf is None:
            raise HTTPException(status_code=500, detail="pool not loaded")

        before = len(pf.models)
        pf.models = [m for m in pf.models if m.model != model_name and (m.alias != model_name)]
        if len(pf.models) == before:
            raise HTTPException(status_code=404, detail=f"unknown model/alias: {model_name}")

        save_pool(state["pool_path"], pf)
        await reload_pool("delete")
        return {"ok": True}

    return app
