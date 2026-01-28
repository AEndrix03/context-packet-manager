import argparse
import json
from pathlib import Path

import faiss

from .component import build_component
from .embedder import JinaCodeEmbedder

def load_docs(docs_path: Path):
    docs = []
    with docs_path.open("r", encoding="utf-8") as f:
        for line in f:
            docs.append(json.loads(line))
    return docs


def cmd_build(args):
    build_component(
        input_dir=args.input_dir,
        component_dir=args.component_dir,
        model_name=args.model,
        max_seq_length=args.max_seq_length,
        lines_per_chunk=args.lines_per_chunk,
        overlap_lines=args.overlap_lines,
    )


def cmd_cpm_build(args):
    build_component(
        input_dir=args.dir,
        component_dir=args.out,
        model_name=args.model,
        max_seq_length=args.max_seq_length,
        lines_per_chunk=args.lines_per_chunk,
        overlap_lines=args.overlap_lines,
    )


def cmd_query(args):
    comp = Path(args.component_dir)

    manifest = json.loads((comp / "manifest.json").read_text(encoding="utf-8"))
    model_name = manifest["embedding"]["model"]
    max_seq_length = int(manifest["embedding"].get("max_seq_length", 1024))

    docs = load_docs(comp / "docs.jsonl")
    index = faiss.read_index(str(comp / "faiss" / "index.faiss"))

    embedder = JinaCodeEmbedder(model_name=model_name, max_seq_length=max_seq_length)
    q = embedder.embed_texts([args.query]).astype("float32")  # già normalized

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


def add_common_build_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default="jinaai/jina-embeddings-v2-base-code")
    parser.add_argument("--max_seq_length", type=int, default=1024)
    parser.add_argument("--lines_per_chunk", type=int, default=80)
    parser.add_argument("--overlap_lines", type=int, default=10)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rag")
    sub = ap.add_subparsers(dest="command", required=True)

    component = sub.add_parser("component", help="Component lifecycle commands")
    component_sub = component.add_subparsers(dest="subcommand", required=True)

    component_build = component_sub.add_parser("build", help="Build a component index")
    component_build.add_argument("--input_dir", required=True)
    component_build.add_argument("--component_dir", required=True)
    add_common_build_args(component_build)
    component_build.set_defaults(func=cmd_build)

    component_query = component_sub.add_parser("query", help="Query a component index")
    component_query.add_argument("--component_dir", required=True)
    component_query.add_argument("--query", required=True)
    component_query.add_argument("-k", type=int, default=5)
    component_query.set_defaults(func=cmd_query)

    cpm = sub.add_parser("cpm", help="Context packet manager")
    cpm_sub = cpm.add_subparsers(dest="subcommand", required=True)

    cpm_build = cpm_sub.add_parser("build", help="Build a context packet")
    cpm_build.add_argument("--dir", default=".")
    cpm_build.add_argument("--out", default=".")
    add_common_build_args(cpm_build)
    cpm_build.set_defaults(func=cmd_cpm_build)

    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
