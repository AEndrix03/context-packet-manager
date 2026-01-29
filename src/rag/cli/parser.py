import argparse

from .commands.build import add_common_build_args, cmd_cpm_build
from .commands.lookup import cmd_cpm_lookup


def _cmd_query(args):
    # Lazy import: query (e quindi HttpEmbedder/faiss) solo quando serve
    from .commands.query import cmd_query
    return cmd_query(args)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rag")
    sub = ap.add_subparsers(dest="command", required=True)

    # CPM commands (single entrypoint)
    cpm = sub.add_parser("cpm", help="Context packet manager")
    cpm_sub = cpm.add_subparsers(dest="subcommand", required=True)

    # cpm embed
    from .commands.embed import add_cpm_embed_commands
    add_cpm_embed_commands(cpm_sub)

    # cpm build
    cpm_build = cpm_sub.add_parser("build", help="Build a context packet")
    cpm_build.add_argument("--dir", default=".")
    cpm_build.add_argument("--out", default=".")
    cpm_build.add_argument("--version", default="0.0.0", help="Set the version for the context packet")
    add_common_build_args(cpm_build)
    cpm_build.set_defaults(func=cmd_cpm_build)

    # cpm lookup
    cpm_lookup = cpm_sub.add_parser("lookup", help="List installed context packets (phase 0: show all)")
    cpm_lookup.add_argument("--cpm_dir", default=".cpm", help="Folder containing extracted packets (default: .cpm)")
    cpm_lookup.add_argument("--format", choices=["text", "jsonl"], default="text",
                            help="Output format (default: text)")
    cpm_lookup.set_defaults(func=cmd_cpm_lookup)

    # cpm query
    cpm_query = cpm_sub.add_parser("query", help="Query an installed packet by name/path under .cpm/")
    cpm_query.add_argument("--cpm_dir", default=".cpm", help="Folder containing extracted packets (default: .cpm)")
    cpm_query.add_argument("--packet", required=True, help="Packet name (folder), or direct path to packet folder")
    cpm_query.add_argument("--query", required=True)
    cpm_query.add_argument("-k", type=int, default=5)
    cpm_query.set_defaults(func=_cmd_query)

    return ap
