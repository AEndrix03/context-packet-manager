import argparse

from .commands.build import (
    add_common_build_args,
    cmd_build,
    cmd_cpm_build,
)
from .commands.query import cmd_query


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rag")
    sub = ap.add_subparsers(dest="command", required=True)

    # packet commands
    packet = sub.add_parser("packet", help="packet lifecycle commands")
    packet_sub = packet.add_subparsers(dest="subcommand", required=True)

    # packet build
    packet_build = packet_sub.add_parser("build", help="Build a packet index")
    packet_build.add_argument("--input_dir", required=True)
    packet_build.add_argument("--packet_dir", required=True)
    add_common_build_args(packet_build)
    packet_build.set_defaults(func=cmd_build)

    # packet query
    packet_query = packet_sub.add_parser("query", help="Query a packet index")
    packet_query.add_argument("--packet_dir", required=True)
    packet_query.add_argument("--query", required=True)
    packet_query.add_argument("-k", type=int, default=5)
    packet_query.set_defaults(func=cmd_query)

    # CPM commands
    cpm = sub.add_parser("cpm", help="Context packet manager")
    cpm_sub = cpm.add_subparsers(dest="subcommand", required=True)

    # cpm build
    cpm_build = cpm_sub.add_parser("build", help="Build a context packet")
    cpm_build.add_argument("--dir", default=".")
    cpm_build.add_argument("--out", default=".")
    cpm_build.add_argument("--version", default="0.0.0", help="Set the version for the context packet")
    add_common_build_args(cpm_build)
    cpm_build.set_defaults(func=cmd_cpm_build)

    return ap
