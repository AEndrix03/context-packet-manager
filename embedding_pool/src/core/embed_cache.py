from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    puts: int = 0


class EmbedCache:
    """
    Persistent cache:
      key   = (model, sha256(text))
      value = embedding vector (stored as float16 blob by default)

    Storage backend: sqlite (single file in cache_dir).
    Thread-safe via a lock (FastAPI can run in multi-thread executors).
    """

    def __init__(self, cache_dir: str, *, db_name: str = "embeddings.sqlite", store_dtype: str = "float16"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.cache_dir / db_name
        self.store_dtype = (store_dtype or "float16").strip().lower()
        if self.store_dtype not in ("float16", "float32"):
            self.store_dtype = "float16"

        self._lock = threading.Lock()
        self.stats = CacheStats()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        # open per-operation connection (safe with threads)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS emb_cache (
                        model TEXT NOT NULL,
                        h     TEXT NOT NULL,
                        dim   INTEGER NOT NULL,
                        dtype TEXT NOT NULL,
                        vec   BLOB NOT NULL,
                        ts    INTEGER NOT NULL,
                        PRIMARY KEY (model, h)
                    );
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_emb_cache_model ON emb_cache(model);")
                conn.commit()
            finally:
                conn.close()

    def get_many(self, model: str, texts: List[str]) -> Tuple[List[str], Dict[int, np.ndarray]]:
        """
        Returns:
          - hashes (aligned with texts)
          - found: dict {index_in_texts -> vector(float32)}
        """
        model = (model or "").strip()
        hashes = [_sha256_text(t) for t in texts]

        if not hashes:
            return hashes, {}

        # SQLite has a limit on the number of host parameters; chunk it.
        found: Dict[int, np.ndarray] = {}
        with self._lock:
            conn = self._connect()
            try:
                # Map hash -> indices (handle duplicates in request)
                h2idx: Dict[str, List[int]] = {}
                for i, h in enumerate(hashes):
                    h2idx.setdefault(h, []).append(i)

                hs = list(h2idx.keys())

                step = 800  # conservative chunk size
                for off in range(0, len(hs), step):
                    part = hs[off: off + step]
                    qmarks = ",".join(["?"] * len(part))
                    rows = conn.execute(
                        f"SELECT h, dim, dtype, vec FROM emb_cache WHERE model=? AND h IN ({qmarks})",
                        [model, *part],
                    ).fetchall()

                    for (h, dim, dtype, blob) in rows:
                        arr = np.frombuffer(blob, dtype=np.float16 if dtype == "float16" else np.float32)
                        arr = arr.reshape((int(dim),))
                        v = arr.astype(np.float32, copy=False)

                        for i in h2idx.get(h, []):
                            found[i] = v

                # stats
                self.stats.hits += len(found)
                self.stats.misses += (len(texts) - len(found))

            finally:
                conn.close()

        return hashes, found

    def put_many(self, model: str, hashes: List[str], vecs: np.ndarray) -> int:
        """
        Insert/update vectors for the given hashes.
        vecs shape: (n, dim), float32 preferred.
        """
        model = (model or "").strip()
        if vecs.ndim != 2:
            raise ValueError("vecs must be 2D")
        n, dim = int(vecs.shape[0]), int(vecs.shape[1])
        if n != len(hashes):
            raise ValueError("hashes length mismatch")

        dtype = self.store_dtype
        if dtype == "float16":
            store = vecs.astype(np.float16, copy=False)
        else:
            store = vecs.astype(np.float32, copy=False)

        ts = int(time.time())
        rows = [(model, hashes[i], dim, dtype, store[i].tobytes(), ts) for i in range(n)]

        with self._lock:
            conn = self._connect()
            try:
                conn.executemany(
                    """
                    INSERT INTO emb_cache(model, h, dim, dtype, vec, ts)
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(model, h) DO UPDATE SET
                        dim=excluded.dim,
                        dtype=excluded.dtype,
                        vec=excluded.vec,
                        ts=excluded.ts
                    """,
                    rows,
                )
                conn.commit()
                self.stats.puts += n
                return n
            finally:
                conn.close()

    def prune_models(self, allowed_models: Iterable[str]) -> int:
        """
        Remove all cache entries for models not in allowed_models.
        """
        allowed = sorted({(m or "").strip() for m in allowed_models if (m or "").strip()})
        with self._lock:
            conn = self._connect()
            try:
                if not allowed:
                    # nothing allowed -> clear all
                    cur = conn.execute("DELETE FROM emb_cache")
                    conn.commit()
                    return int(cur.rowcount or 0)

                qmarks = ",".join(["?"] * len(allowed))
                cur = conn.execute(
                    f"DELETE FROM emb_cache WHERE model NOT IN ({qmarks})",
                    allowed,
                )
                conn.commit()
                return int(cur.rowcount or 0)
            finally:
                conn.close()

    def clear_model(self, model: str) -> int:
        model = (model or "").strip()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM emb_cache WHERE model=?", [model])
                conn.commit()
                return int(cur.rowcount or 0)
            finally:
                conn.close()

    def vacuum(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("VACUUM")
                conn.commit()
            finally:
                conn.close()
