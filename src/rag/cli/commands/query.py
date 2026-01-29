import json
import os
from pathlib import Path

import faiss

from ...embedding.http_embedder import HttpEmbedder


def load_docs(docs_path: Path):
    docs = []
    with docs_path.open("r", encoding="utf-8") as f:
        for line in f:
            docs.append(json.loads(line))
    return docs


def _resolve_packet_dir(cpm_dir: Path, packet: str) -> Path | None:
    packet_arg = Path(packet)
    if packet_arg.exists() and packet_arg.is_dir():
        return packet_arg

    candidate = cpm_dir / packet
    if candidate.exists() and candidate.is_dir():
        return candidate

    return None


def cmd_query(args) -> None:
    cpm_dir = Path(args.cpm_dir)
    packet_dir = _resolve_packet_dir(cpm_dir, args.packet)

    if packet_dir is None:
        tried = (cpm_dir / args.packet).resolve()
        print(f"[cpm:query] packet not found: {args.packet}")
        print(f"           tried: {tried}")
        return

    comp = packet_dir

    manifest = json.loads((comp / "manifest.json").read_text(encoding="utf-8"))
    model_name = manifest["embedding"]["model"]
    max_seq_length = int(manifest["embedding"].get("max_seq_length", 1024))

    docs = load_docs(comp / "docs.jsonl")
    index = faiss.read_index(str(comp / "faiss" / "index.faiss"))

    embed_url = os.environ.get("RAG_EMBED_URL", "http://127.0.0.1:8765")
    client = HttpEmbedder(embed_url)

    if not client.health():
        print(f"[error] embedding server not reachable at {embed_url}")
        print("        - start it with: rag cpm embed start-server --detach")
        print("        - or set RAG_EMBED_URL")
        return

    q = client.embed_texts(
        [args.query],
        model_name=model_name,
        max_seq_length=max_seq_length,
        normalize=True,
        dtype="float32",
        show_progress=False,
    )

    scores, ids = index.search(q, args.k)
    scores, ids = scores[0], ids[0]

    print(f"[cpm:query] '{args.query}' (k={args.k}) packet={comp.name}")
    for r, (idx, sc) in enumerate(zip(ids, scores), 1):
        if idx < 0:
            continue
        d = docs[int(idx)]
        meta = d.get("metadata", {})
        print(f"\n#{r} score={float(sc):.4f} id={d.get('id')}")
        if meta.get("path"):
            print(f"   path={meta['path']} lines={meta.get('line_start')}-{meta.get('line_end')}")
        print(d["text"])
