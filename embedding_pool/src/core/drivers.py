from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence, Union

import numpy as np

from .util import safe_bool, safe_int


class EmbedDriver(Protocol):
    def embed(self, texts: List[str], options: Dict[str, Any]) -> np.ndarray: ...

    def dim(self) -> int: ...

    def warmup(self) -> None: ...


@dataclass
class LocalSTDriver:
    model_name: str
    _model: Any = None
    _dim: Optional[int] = None

    def _load(self):
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self.model_name, trust_remote_code=True)
        self._dim = int(self._model.get_sentence_embedding_dimension())

    def warmup(self) -> None:
        self._load()
        # usa una frase breve per caricare il modello in memoria (VRAM)
        self.embed(["warmup"], {})

    def dim(self) -> int:
        self._load()
        return int(self._dim or 0)

    def embed(self, texts: List[str], options: Dict[str, Any]) -> np.ndarray:
        self._load()
        max_seq = safe_int(options.get("max_seq_length"), 1024)
        normalize = safe_bool(options.get("normalize"), True)
        dtype = str(options.get("dtype") or "float32").strip().lower()

        try:
            self._model.max_seq_length = int(max_seq)
        except Exception:
            pass

        v = self._model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=bool(options.get("show_progress") or False),
        )
        v = v.astype("float32")

        if v.ndim == 1:
            v = v.reshape(1, -1)

        if normalize:
            denom = np.linalg.norm(v, axis=1, keepdims=True) + 1e-12
            v = v / denom

        if dtype == "float16":
            v = v.astype("float16", copy=False)
        else:
            v = v.astype("float32", copy=False)

        return v


@dataclass
class HttpDriver:
    base_url: str
    remote_model: str
    timeout_s: Optional[float] = None
    _dim: Optional[int] = None

    def warmup(self) -> None:
        pass

    def dim(self) -> int:
        return int(self._dim or 0)

    def embed(self, texts: List[str], options: Dict[str, Any]) -> np.ndarray:
        import requests

        payload = {
            "model": self.remote_model,
            "texts": texts,
            "options": options,
        }
        r = requests.post(
            f"{self.base_url.rstrip('/')}/embed",
            json=payload,
            timeout=self.timeout_s or 120.0,
        )
        r.raise_for_status()
        j = r.json()
        vecs = np.array(j["vectors"], dtype=np.float32)
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        self._dim = int(vecs.shape[1])
        return vecs


class SubprocessDriver:
    """
    Driver che delega l'embedding a un processo worker dedicato.

    Protocollo: JSON-lines su stdin/stdout.
      request:  {"id": N, "texts": [...], "options": {...}}
      response: {"id": N, "ok": true, "vectors": [[...]], "dim": d}
                {"id": N, "ok": false, "error": "...", "trace": "..."}
    """

    def __init__(
            self,
            model_name: str,
            cmd: Sequence[str],
            *,
            cwd: Optional[str] = None,
            env: Optional[Dict[str, str]] = None,
            startup_timeout_s: float = 60.0,
            timeout_s: float = 120.0,
    ):
        self.model_name = model_name
        self.cmd = list(cmd)
        self.cwd = cwd
        self.env = dict(env or {})
        self.startup_timeout_s = float(startup_timeout_s)
        self.timeout_s = float(timeout_s)

        self._proc: Optional[subprocess.Popen[str]] = None
        self._lock = threading.Lock()
        self._next_id = 0
        self._dim: Optional[int] = None

        # Drain stderr to avoid deadlocks (transformers can be chatty).
        self._stderr_ring: collections.deque[str] = collections.deque(maxlen=2000)
        self._stderr_thread: Optional[threading.Thread] = None
        self._stderr_stop = threading.Event()

    def dim(self) -> int:
        return int(self._dim or 0)

    def close(self) -> None:
        with self._lock:
            p = self._proc
            self._proc = None
        if not p:
            return
        try:
            self._stderr_stop.set()
        except Exception:
            pass
        try:
            if p.stdin:
                try:
                    p.stdin.write(json.dumps({"op": "shutdown"}) + "\n")
                    p.stdin.flush()
                except Exception:
                    pass
            p.terminate()
        except Exception:
            pass
        try:
            p.wait(timeout=2.0)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

    def warmup(self) -> None:
        with self._lock:
            self._ensure_started()

    def _start_stderr_drain(self, p: subprocess.Popen[str]) -> None:
        if self._stderr_thread is not None and self._stderr_thread.is_alive():
            return
        if p.stderr is None:
            return
        self._stderr_stop.clear()

        def _drain() -> None:
            try:
                for raw in p.stderr:
                    if self._stderr_stop.is_set():
                        break
                    line = raw.rstrip("\r\n")
                    if line:
                        self._stderr_ring.append(line)
            except Exception:
                pass

        self._stderr_thread = threading.Thread(target=_drain, daemon=True)
        self._stderr_thread.start()

    def _stderr_tail(self, max_lines: int = 200) -> str:
        if not self._stderr_ring:
            return ""
        tail = list(self._stderr_ring)[-max_lines:]
        return "\n".join(tail)

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return

        env = os.environ.copy()
        env.update(self.env)
        env["EMBEDPOOL_MODEL"] = self.model_name

        p = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=self.cwd,
            env=env,
        )

        # Drain stderr immediately to prevent deadlocks.
        self._start_stderr_drain(p)

        # handshake: il worker stampa una riga "READY ..."
        ready_line = _readline_with_timeout(p, self.startup_timeout_s)
        if ready_line is None:
            self._terminate_with_context(p, "worker startup timeout")
        if not ready_line.startswith("READY"):
            self._terminate_with_context(p, f"worker handshake failed: {ready_line!r}")

        self._proc = p

    def _terminate_with_context(self, p: subprocess.Popen[str], msg: str) -> None:
        err = self._stderr_tail()
        try:
            p.terminate()
        except Exception:
            pass
        raise RuntimeError(f"{msg}" + (f". stderr (tail):\n{err}" if err else ""))

    def embed(self, texts: List[str], options: Dict[str, Any]) -> np.ndarray:
        with self._lock:
            self._ensure_started()
            assert self._proc is not None
            p = self._proc

            self._next_id += 1
            rid = self._next_id

            req = {"id": rid, "texts": texts, "options": options}
            assert p.stdin is not None
            p.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            p.stdin.flush()

            line = _readline_with_timeout(p, self.timeout_s)
            if line is None:
                self._proc = None
                self._terminate_with_context(p, "worker request timeout")

            try:
                resp = json.loads(line)
            except Exception:
                err = self._stderr_tail()
                raise RuntimeError(
                    f"invalid worker response: {line!r}"
                    + (f". stderr (tail):\n{err}" if err else "")
                )

            if int(resp.get("id") or -1) != rid:
                raise RuntimeError(f"worker response id mismatch: got {resp.get('id')} expected {rid}")

            if not resp.get("ok", False):
                err = str(resp.get("error") or "worker error")
                trace = str(resp.get("trace") or "")
                raise RuntimeError(err + (("\n" + trace) if trace else ""))

            vecs = np.array(resp["vectors"], dtype=np.float32)
            if vecs.ndim == 1:
                vecs = vecs.reshape(1, -1)
            self._dim = int(resp.get("dim") or vecs.shape[1])
            return vecs


def _readline_with_timeout(p: subprocess.Popen[str], timeout_s: float) -> Optional[str]:
    """Legge una linea da stdout con timeout. Usa un thread per non bloccare."""
    out = {"line": None}

    def _reader():
        try:
            if p.stdout is None:
                return
            out["line"] = p.stdout.readline()
        except Exception:
            out["line"] = None

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        return None
    line = out["line"]
    if line is None:
        return None
    return line.rstrip("\r\n")


def _drain_stderr(p: subprocess.Popen[str], max_bytes: int = 16_384) -> str:
    """Best-effort stderr drain.

    NOTE: reading stderr of a *running* process can block; this function intentionally returns
    empty string if the process is still alive.
    """
    try:
        if p.stderr is None:
            return ""
        if p.poll() is None:
            return ""
        data = p.stderr.read(max_bytes)
        return data or ""
    except Exception:
        return ""


def _default_worker_cmd() -> List[str]:
    # usa l'interprete corrente per default
    return [sys.executable, "-m", "embedding_pool.worker"]


def build_driver(model_name: str, driver_type: str, cfg: Dict[str, Any]) -> EmbedDriver:
    t = (driver_type or "").strip()
    if t == "local_st":
        return LocalSTDriver(model_name=model_name)
    if t == "http":
        base_url = str(cfg.get("base_url") or "").strip()
        remote_model = str(cfg.get("remote_model") or model_name).strip()
        timeout_s = cfg.get("timeout_s")
        timeout_s = float(timeout_s) if timeout_s is not None else None
        if not base_url:
            raise ValueError("http driver requires config.base_url")
        return HttpDriver(base_url=base_url, remote_model=remote_model, timeout_s=timeout_s)
    if t == "subprocess":
        cmd: Union[str, Sequence[str], None] = cfg.get("cmd")
        if not cmd:
            cmd_list = _default_worker_cmd()
        elif isinstance(cmd, str):
            # split molto semplice (spazi). Se ti servono quote, passa una lista.
            cmd_list = [c for c in cmd.strip().split(" ") if c]
        else:
            cmd_list = list(cmd)

        cwd = cfg.get("cwd")
        cwd = str(cwd) if cwd else None

        env = cfg.get("env") or {}
        if not isinstance(env, dict):
            env = {}
        env = {str(k): str(v) for k, v in env.items()}

        startup_timeout_s = float(cfg.get("startup_timeout_s") or 60.0)
        timeout_s = float(cfg.get("timeout_s") or 120.0)

        return SubprocessDriver(
            model_name=model_name,
            cmd=cmd_list,
            cwd=cwd,
            env=env,
            startup_timeout_s=startup_timeout_s,
            timeout_s=timeout_s,
        )
    raise ValueError(f"unsupported driver type: {t!r}")
