from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .drivers import build_driver, EmbedDriver
from .types import ModelSpec
from .util import now_ms


@dataclass
class WorkItem:
    model: str
    texts: List[str]
    options: Dict[str, Any]
    fut: "asyncio.Future[Tuple[np.ndarray, int, Dict[str, Any]]]"
    created_ms: int


@dataclass
class Replica:
    replica_id: str
    driver: EmbedDriver
    inflight: int = 0
    last_idle_ms: int = 0
    state: str = "IDLE"  # IDLE|BUSY|STOPPING
    task: Optional[asyncio.Task] = None


class ModelRuntime:
    def __init__(self, spec: ModelSpec, global_sem: asyncio.Semaphore):
        self.spec = spec
        self.global_sem = global_sem
        self.queue: asyncio.Queue[Optional[WorkItem]] = asyncio.Queue(maxsize=int(spec.queue.max_size))
        self.replicas: List[Replica] = []
        self._replica_counter = 0
        self._lock = asyncio.Lock()
        self._scaler_task: Optional[asyncio.Task] = None
        self._running = False

    def status(self) -> Dict[str, Any]:
        idle = sum(1 for r in self.replicas if r.state == "IDLE")
        busy = sum(1 for r in self.replicas if r.state == "BUSY")
        return {
            "model": self.spec.model,
            "alias": self.spec.alias,
            "enabled": self.spec.enabled,
            "driver_type": self.spec.driver.type,
            "replicas": len(self.replicas),
            "replicas_idle": idle,
            "replicas_busy": busy,
            "queue_len": self.queue.qsize(),
            "scaling": {"min": self.spec.scaling.min, "max": self.spec.scaling.max,
                        "idle_ttl_s": self.spec.scaling.idle_ttl_s},
        }

    async def start(self) -> None:
        async with self._lock:
            if self._running:
                return
            self._running = True
            for _ in range(max(0, int(self.spec.scaling.min))):
                await self._add_replica_locked()
            self._scaler_task = asyncio.create_task(self._scaler_loop())

    async def stop(self) -> None:
        # Stop scaler + replicas, fail pending requests, and drain queue.
        async with self._lock:
            self._running = False
            if self._scaler_task:
                self._scaler_task.cancel()
                self._scaler_task = None

            # Mark replicas stopping, close drivers, cancel tasks.
            for r in list(self.replicas):
                r.state = "STOPPING"
                self._close_driver(r.driver)
                if r.task:
                    r.task.cancel()

            # Wake up any replica blocked on queue.get()
            for _ in range(len(self.replicas)):
                try:
                    self.queue.put_nowait(None)
                except asyncio.QueueFull:
                    break

            # Fail everything still queued
            while not self.queue.empty():
                item = self.queue.get_nowait()
                if item is not None and not item.fut.done():
                    item.fut.set_exception(RuntimeError("model runtime stopped"))
                self.queue.task_done()

            self.replicas.clear()

    async def enqueue(self, texts: List[str], options: Dict[str, Any]) -> Tuple[np.ndarray, int, Dict[str, Any]]:
        if not self.spec.enabled:
            raise RuntimeError(f"model disabled: {self.spec.model}")

        fut: asyncio.Future[Tuple[np.ndarray, int, Dict[str, Any]]] = asyncio.get_running_loop().create_future()
        item = WorkItem(
            model=self.spec.model,
            texts=texts,
            options=options,
            fut=fut,
            created_ms=now_ms(),
        )
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            raise RuntimeError(f"queue full for model: {self.spec.model}")

        await self._maybe_scale_up()
        return await fut

    async def _maybe_scale_up(self) -> None:
        async with self._lock:
            if not self._running:
                return
            if len(self.replicas) >= int(self.spec.scaling.max):
                return
            if any(r.state == "IDLE" for r in self.replicas):
                return
            if self.queue.qsize() > 0:
                await self._add_replica_locked()

    async def _add_replica_locked(self) -> None:
        self._replica_counter += 1
        rid = f"{self.spec.model}#{self._replica_counter}"
        driver = build_driver(self.spec.model, self.spec.driver.type, self.spec.driver.config or {})
        await asyncio.to_thread(driver.warmup)
        rep = Replica(replica_id=rid, driver=driver, last_idle_ms=now_ms(), state="IDLE")
        self.replicas.append(rep)
        rep.task = asyncio.create_task(self._replica_loop(rep))

    async def _replica_loop(self, rep: Replica) -> None:
        while self._running and rep.state != "STOPPING":
            item = await self.queue.get()
            if item is None:
                self.queue.task_done()
                break
            rep.state = "BUSY"
            rep.inflight += 1
            async with self.global_sem:
                try:
                    arr, dim = await asyncio.to_thread(self._embed_sync, rep.driver, item.texts, item.options)
                    meta = {"replica_id": rep.replica_id}
                    if not item.fut.done():
                        item.fut.set_result((arr, dim, meta))
                except Exception as e:
                    if not item.fut.done():
                        item.fut.set_exception(e)
                finally:
                    rep.inflight -= 1
            rep.last_idle_ms = now_ms()
            rep.state = "IDLE"
            self.queue.task_done()

    @staticmethod
    def _embed_sync(driver: EmbedDriver, texts: List[str], options: Dict[str, Any]) -> Tuple[np.ndarray, int]:
        arr = driver.embed(texts, options)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        dim = int(arr.shape[1]) if arr.ndim == 2 else int(driver.dim())
        if arr.dtype != np.float32:
            arr = arr.astype("float32")
        return arr, dim

    @staticmethod
    def _close_driver(driver: EmbedDriver) -> None:
        # opzionale: alcuni driver (subprocess) espongono close()
        try:
            close = getattr(driver, "close", None)
            if callable(close):
                close()
        except Exception:
            pass

    async def _scaler_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(0.5)
                await self._apply_scaling()
            except asyncio.CancelledError:
                return
            except Exception:
                continue

    async def _apply_scaling(self) -> None:
        async with self._lock:
            if not self._running:
                return
            while len(self.replicas) < int(self.spec.scaling.min):
                await self._add_replica_locked()

            if len(self.replicas) <= int(self.spec.scaling.min):
                return

            ttl_ms = int(self.spec.scaling.idle_ttl_s) * 1000
            now = now_ms()

            removable = []
            for r in self.replicas:
                if len(self.replicas) - len(removable) <= int(self.spec.scaling.min):
                    break
                if r.state == "IDLE" and (now - r.last_idle_ms) >= ttl_ms:
                    removable.append(r)

            for r in removable:
                r.state = "STOPPING"
                self._close_driver(r.driver)
                if r.task:
                    r.task.cancel()
                try:
                    self.replicas.remove(r)
                except ValueError:
                    pass
