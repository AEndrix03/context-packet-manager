import json
from pathlib import Path

import faiss


def load_docs(docs_path: Path):
    docs = []
    with docs_path.open("r", encoding="utf-8") as f:
        for line in f:
            docs.append(json.loads(line))
    return docs


def cmd_query(args):
    comp = Path(args.packet_dir)

    manifest = json.loads((comp / "manifest.json").read_text(encoding="utf-8"))
    model_name = manifest["embedding"]["model"]
    max_seq_length = int(manifest["embedding"].get("max_seq_length", 1024))

    docs = load_docs(comp / "docs.jsonl")
    index = faiss.read_index(str(comp / "faiss" / "index.faiss"))

    # Lazy import: evita di caricare transformers quando non serve
    from ...embedder import JinaCodeEmbedder

    embedder = JinaCodeEmbedder(model_name=model_name, max_seq_length=max_seq_length)
    q = embedder.embed_texts([args.query]).astype("float32")

    scores, ids = index.search(q, args.k)
    scores, ids = scores[0], ids[0]

    print(f"[query] '{args.query}' (k={args.k})")
    for r, (idx, sc) in enumerate(zip(ids, scores), 1):
        if idx < 0:
            continue
        d = docs[int(idx)]
        meta = d.get("metadata", {})
        print(f"\n#{r} score={float(sc):.4f} id={d.get('id')}")
        if meta.get("path"):
            print(f"   path={meta['path']} lines={meta.get('line_start')}-{meta.get('line_end')}")
        print(d["text"])
