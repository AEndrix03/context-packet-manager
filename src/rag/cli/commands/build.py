import argparse

from ...packet import build_packet


def cmd_build(args):
    build_packet(
        input_dir=args.input_dir,
        packet_dir=args.packet_dir,
        model_name=args.model,
        max_seq_length=args.max_seq_length,
        lines_per_chunk=args.lines_per_chunk,
        overlap_lines=args.overlap_lines,
        archive=args.archive,
        archive_format=args.archive_format,
    )


def cmd_cpm_build(args):
    build_packet(
        input_dir=args.dir,
        packet_dir=args.out,
        model_name=args.model,
        max_seq_length=args.max_seq_length,
        lines_per_chunk=args.lines_per_chunk,
        overlap_lines=args.overlap_lines,
        archive=args.archive,
        archive_format=args.archive_format,
        version=args.version,
    )


def add_common_build_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default="jinaai/jina-embeddings-v2-base-code")
    parser.add_argument("--max_seq_length", type=int, default=1024)
    parser.add_argument("--lines_per_chunk", type=int, default=80)
    parser.add_argument("--overlap_lines", type=int, default=10)
    parser.add_argument("--archive", action=argparse.BooleanOptionalAction, default=True,
                        help="Create a compressed archive alongside the packet directory (default: enabled)")
    parser.add_argument("--archive_format", choices=["tar.gz", "zip"], default="tar.gz",
                        help="Archive format (default: tar.gz)")


