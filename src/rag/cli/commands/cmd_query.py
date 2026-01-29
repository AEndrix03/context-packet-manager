from pathlib import Path


def cmd_cpm_query(args) -> None:
    cpm_dir = Path(args.cpm_dir)

    packet_arg = Path(args.packet)
    if packet_arg.exists() and packet_arg.is_dir():
        packet_dir = packet_arg
    else:
        packet_dir = cpm_dir / args.packet

    if not packet_dir.exists() or not packet_dir.is_dir():
        print(f"[cpm:query] packet not found: {args.packet}")
        print(f"           tried: {packet_dir.resolve()}")
        return

    # Reuse the existing packet query logic
    from .query import cmd_query

    class _Shim:
        # cmd_query si aspetta args.packet_dir / args.query / args.k
        packet_dir = str(packet_dir)
        query = args.query
        k = args.k

    cmd_query(_Shim)
