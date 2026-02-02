from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any, Dict, List

import numpy as np


# Worker dedicato per modello.
# Carica il modello indicato da EMBEDPOOL_MODEL e risponde su stdin/stdout (JSON lines).


def _safe_int(x, default: int) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _safe_bool(x, default: bool) -> bool:
    if x is None:
        return default
    if isinstance(x, bool):
        return x
    s = str(x).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


class _LocalST:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name, trust_remote_code=True)
        self.dim = int(self.model.get_sentence_embedding_dimension())

    def embed(self, texts: List[str], options: Dict[str, Any]) -> np.ndarray:
        max_seq = _safe_int(options.get("max_seq_length"), 1024)
        normalize = _safe_bool(options.get("normalize"), True)

        try:
            self.model.max_seq_length = int(max_seq)
        except Exception:
            pass

        v = self.model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=bool(options.get("show_progress") or False),
        ).astype("float32")

        if v.ndim == 1:
            v = v.reshape(1, -1)

        if normalize:
            denom = np.linalg.norm(v, axis=1, keepdims=True) + 1e-12
            v = v / denom

        return v.astype("float32", copy=False)


def main() -> int:
    model_name = (os.environ.get("EMBEDPOOL_MODEL") or "").strip()
    if not model_name:
        print("ERR missing EMBEDPOOL_MODEL", flush=True)
        return 2

    # Per ora: solo sentence-transformers (ST).
    # Il punto è che questo file gira nella venv dedicata a quel modello,
    # quindi puoi avere transformers diversi per modelli diversi.
    driver = _LocalST(model_name)

    # handshake per il parent
    print(f"READY model={model_name} dim={driver.dim}", flush=True)

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue

        if msg.get("op") == "shutdown":
            break

        rid = msg.get("id")
        texts = msg.get("texts") or []
        options = msg.get("options") or {}
        try:
            vecs = driver.embed(list(texts), dict(options))
            out = {"id": rid, "ok": True, "vectors": vecs.tolist(), "dim": int(vecs.shape[1])}
        except Exception as e:
            out = {
                "id": rid,
                "ok": False,
                "error": str(e),
                "trace": traceback.format_exc(limit=20),
            }

        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
