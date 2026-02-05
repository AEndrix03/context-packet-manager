# rag/cli/parser.py
import argparse

from cli.commands.build import add_common_build_args, cmd_cpm_build
from cli.commands.lookup import cmd_cpm_lookup


def _cmd_query(args):
    from cli.commands.query import cmd_query
    return cmd_query(args)


def _cmd_mcp_serve(args):
    from cpm_mcp.server import main as mcp_server_main
    return mcp_server_main()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cpm")
    sub = ap.add_subparsers(dest="subcommand", required=True)

    # embed
    from cli.commands.embed import add_cpm_embed_commands
    add_cpm_embed_commands(sub)

    # build
    cpm_build = sub.add_parser("build", help="Build a context packet")
    cpm_build.add_argument("--dir", default=".")
    cpm_build.add_argument("--out", default=".")
    cpm_build.add_argument("--version", default="0.0.0", help="Set the version for the context packet")
    add_common_build_args(cpm_build)
    cpm_build.set_defaults(func=cmd_cpm_build)

    # lookup (local)
    cpm_lookup = sub.add_parser("lookup", help="List installed context packets")
    cpm_lookup.add_argument("--cpm_dir", default=".cpm")
    cpm_lookup.add_argument("--format", choices=["text", "jsonl"], default="text")
    cpm_lookup.add_argument("--all-versions", action="store_true",
                            help="Show all installed versions (default: current only)")
    cpm_lookup.set_defaults(func=cmd_cpm_lookup)

    # query
    cpm_query = sub.add_parser("query", help="Query an installed packet by name/path under .cpm/")
    cpm_query.add_argument("--cpm_dir", default=".cpm")
    cpm_query.add_argument("--packet", required=True, help="Packet name (folder), or direct path to packet folder")
    cpm_query.add_argument("--query", required=True)
    cpm_query.add_argument("-k", type=int, default=5)
    cpm_query.add_argument(
        "--metadata",
        "-m",
        action="append",
        default=[],
        help="Limit results to docs whose metadata matches KEY=VALUE (repeatable)",
    )
    cpm_query.add_argument("--no-cache", action="store_true")
    cpm_query.add_argument("--cache-refresh", action="store_true")
    cpm_query.set_defaults(func=_cmd_query)

    # publish
    from cli.commands.publish import cmd_cpm_publish
    cpm_pub = sub.add_parser("publish", help="Publish a built packet to a registry")
    cpm_pub.add_argument("--from", dest="from_dir", default=".", help="Built packet directory (default: .)")
    cpm_pub.add_argument("--registry", required=True, help="Registry base url (e.g. http://127.0.0.1:8786)")
    cpm_pub.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite package if it already exists on registry (asks confirmation)",
    )
    cpm_pub.add_argument("--yes", action="store_true", help="Assume yes for prompts")
    cpm_pub.set_defaults(func=cmd_cpm_publish)

    # install
    from cli.commands.install import cmd_cpm_install
    cpm_ins = sub.add_parser("install", help="Install packet from registry into .cpm/")
    cpm_ins.add_argument("spec", help="name or name@<version|latest>")
    cpm_ins.add_argument("--registry", required=True)
    cpm_ins.add_argument("--cpm_dir", default=".cpm")
    cpm_ins.set_defaults(func=cmd_cpm_install)

    # uninstall
    from cli.commands.uninstall import cmd_cpm_uninstall
    cpm_un = sub.add_parser("uninstall", help="Uninstall a packet or a specific version")
    cpm_un.add_argument("spec", help="name or name@<version|latest>")
    cpm_un.add_argument("--registry", default="", help="Required if using @latest")
    cpm_un.add_argument("--cpm_dir", default=".cpm")
    cpm_un.set_defaults(func=cmd_cpm_uninstall)

    # update
    from cli.commands.update import cmd_cpm_update
    cpm_up = sub.add_parser("update", help="Update an installed packet (optionally to a target version)")
    cpm_up.add_argument("spec", help="name or name@<version|latest>")
    cpm_up.add_argument("--registry", required=True)
    cpm_up.add_argument("--cpm_dir", default=".cpm")
    cpm_up.add_argument("--purge", action="store_true", help="Remove packet then install version fresh")
    cpm_up.set_defaults(func=cmd_cpm_update)

    # use (pin)
    from cli.commands.use import cmd_cpm_use
    cpm_use = sub.add_parser("use", help="Switch current version (pin) without downloading")
    cpm_use.add_argument("spec", help="name@<version|latest>")
    cpm_use.add_argument("--registry", default="", help="Required if using @latest")
    cpm_use.add_argument("--cpm_dir", default=".cpm")
    cpm_use.set_defaults(func=cmd_cpm_use)

    # list-remote
    from cli.commands.list_remote import cmd_cpm_list_remote
    cpm_lr = sub.add_parser("list-remote", help="List versions available on registry")
    cpm_lr.add_argument("name")
    cpm_lr.add_argument("--registry", required=True)
    cpm_lr.add_argument("--include-yanked", action="store_true")
    cpm_lr.add_argument("--format", choices=["text", "json"], default="text")
    cpm_lr.add_argument("--sort-semantic", action="store_true")
    cpm_lr.set_defaults(func=cmd_cpm_list_remote)

    # prune
    from cli.commands.prune import cmd_cpm_prune
    cpm_pr = sub.add_parser("prune", help="Remove old local versions, keep N latest")
    cpm_pr.add_argument("name")
    cpm_pr.add_argument("--keep", type=int, default=1)
    cpm_pr.add_argument("--cpm_dir", default=".cpm")
    cpm_pr.set_defaults(func=cmd_cpm_prune)

    # cache clear
    from cli.commands.cache import cmd_cpm_cache_clear
    cpm_cache = sub.add_parser("cache", help="Cache management")
    cpm_cache_sub = cpm_cache.add_subparsers(dest="cache_cmd", required=True)

    cpm_cache_clear = cpm_cache_sub.add_parser("clear", help="Clear query cache for current version of a packet")
    cpm_cache_clear.add_argument("--cpm_dir", default=".cpm")
    cpm_cache_clear.add_argument("--packet", required=True)
    cpm_cache_clear.set_defaults(func=cmd_cpm_cache_clear)

    # mcp
    cpm_mcp = sub.add_parser("mcp", help="Model Context Protocol (MCP) server for CPM")
    cpm_mcp_sub = cpm_mcp.add_subparsers(dest="mcp_subcommand", required=True)
    cpm_mcp_serve = cpm_mcp_sub.add_parser("serve", help="Start MCP server (stdio)")
    cpm_mcp_serve.set_defaults(func=_cmd_mcp_serve)

    return ap
